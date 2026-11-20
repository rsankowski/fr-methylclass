#!/usr/bin/env python3
"""fr-methylclass GUI: a local web front end for the Nextflow pipeline.

Python standard library only (no pip installs). The server listens on
127.0.0.1, serves a single page, and launches `nextflow run main.nf` with a
JSON params file. Nextflow runs in its own session with its output written to
a log file in the run's output folder, so a run keeps going if the GUI is
closed, and the GUI picks it up again when it is reopened.

    python3 gui/server.py [--port 8780] [--no-browser]

EXPERIMENTAL. RESEARCH USE ONLY.
"""
import argparse
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GUI_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(GUI_DIR)
MAIN_NF = os.path.join(REPO_DIR, "main.nf")
STATIC_DIR = os.path.join(GUI_DIR, "static")
SETTINGS_FILE = os.path.join(GUI_DIR, "settings.json")
HISTORY_FILE = os.path.join(GUI_DIR, "history.json")
DEFAULT_PORT = 8780

LOG_NAME = "fr-methylclass-gui.log"       # nextflow stdout/stderr, inside the run folder
STATE_NAME = ".fr-methylclass-gui"         # pid / exit-code / params, inside the run folder

ALL_TOOLS = ["crossnn", "methylyzr", "sturgeon", "lamprey", "cnv",
             "rapidcns2", "metagenomics", "report"]
TOOL_GENOME = {"crossnn": "hg19", "methylyzr": "hg38", "sturgeon": "chm13",
               "lamprey": "hg38", "cnv": "hg38", "rapidcns2": "hg38"}
# what main.nf looks for under --assets_dir, and the explicit param that overrides it
TOOL_ASSETS = {
    "crossnn": [("crossnn_model_capper", "crossnn/Capper_et_al_NN.pkl"),
                ("crossnn_model_pancan", "crossnn/pancan_devel_v5i_NN.pkl")],
    "methylyzr": [("methylyzr_epic_bed", "methylyzr/EPIC_CpGannotation.bed"),
                  ("methylyzr_betas", "methylyzr/betas_mean.feather"),
                  ("methylyzr_weights", "methylyzr/W_RELIEF.feather"),
                  ("methylyzr_priors", "methylyzr/class_priors.csv")],
    "sturgeon": [("sturgeon_model", "sturgeon/cns-v2.5.zip")],
    "lamprey": [("lamprey_model", "lamprey/model")],
}
RESTRICTED_IMAGES = {"crossnn", "methylyzr", "sturgeon", "lamprey"}
CONTAINER_PROFILES = {"docker", "podman", "singularity", "apptainer"}

DEFAULT_SETTINGS = {
    "nextflow_bin": "",            # blank = find `nextflow` on PATH
    "profile": "docker",           # docker | podman | singularity | apptainer | host | none
    "gpu": False,
    "slurm": False,
    "hg19_fasta": "",
    "hg38_fasta": "",
    "chm13_fasta": "",
    "assets_dir": "",
    "container_registry": "",      # blank = pipeline default (ghcr.io/rsankowski)
    "restricted_registry": "",     # blank = pipeline default (methylclass)
    "max_cpus": "",
    "max_memory": "",
    "config_file": "",             # extra -c config
    "extra_params": "",            # key = value lines, applied to every run
    "runs_root": os.path.join(os.path.expanduser("~"), "fr-methylclass-runs"),
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".pdf": "application/pdf", ".json": "application/json",
    ".txt": "text/plain; charset=utf-8", ".tsv": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
}

LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# settings + history
# ---------------------------------------------------------------------------
def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    s.update({k: v for k, v in _read_json(SETTINGS_FILE, {}).items() if k in DEFAULT_SETTINGS})
    return s


def save_settings(new):
    s = load_settings()
    for k in DEFAULT_SETTINGS:
        if k in new:
            v = new[k]
            s[k] = v.strip() if isinstance(v, str) else v
    _write_json(SETTINGS_FILE, s)
    return s


def load_history():
    return _read_json(HISTORY_FILE, [])


def save_history(h):
    _write_json(HISTORY_FILE, h)


def nextflow_bin(settings):
    nf = (settings.get("nextflow_bin") or "").strip()
    if nf:
        return os.path.expanduser(nf)
    found = shutil.which("nextflow")
    if found:
        return found
    for cand in ("~/bin/nextflow", "~/.local/bin/nextflow", "~/software/nextflow/nextflow",
                 "/usr/local/bin/nextflow", "/opt/nextflow/nextflow"):
        p = os.path.expanduser(cand)
        if os.access(p, os.X_OK):
            return p
    return "nextflow"


# ---------------------------------------------------------------------------
# input discovery (mirrors discoverSamples() in main.nf)
# ---------------------------------------------------------------------------
def _stem(name):
    return re.sub(r"(?i)\.bam$", "", name)


def discover_samples(paths, group_by):
    groups, warnings = {}, []

    def add(name, bam):
        groups.setdefault(name, set()).add(bam)

    for raw in paths:
        raw = raw.strip()
        if not raw:
            continue
        p = os.path.abspath(os.path.expanduser(raw))
        if not os.path.exists(p):
            warnings.append("Not found: " + raw)
            continue
        if os.path.isfile(p) and p.lower().endswith(".csv"):
            try:
                with open(p, newline="") as fh:
                    for row in csv.DictReader(fh):
                        s, b = (row.get("sample") or "").strip(), (row.get("bam") or "").strip()
                        if not s or not b:
                            warnings.append(f"{raw}: needs columns 'sample' and 'bam'")
                            break
                        if not os.path.isfile(b):
                            warnings.append(f"{raw}: BAM not found: {b}")
                        add(s, b)
            except OSError as e:
                warnings.append(f"{raw}: {e}")
        elif os.path.isfile(p):
            if p.lower().endswith(".bam"):
                add(_stem(os.path.basename(p)), p)
            else:
                warnings.append("Not a .bam or .csv: " + raw)
        else:
            for root, dirs, files in os.walk(p, followlinks=True):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.lower().endswith(".bam"):
                        name = _stem(f) if group_by == "file" else os.path.basename(root)
                        add(name, os.path.join(root, f))
    out = []
    for name in sorted(groups):
        bams = sorted(groups[name])
        size = 0
        for b in bams:
            try:
                size += os.path.getsize(b)
            except OSError:
                pass
        out.append({"sample": name, "n_bams": len(bams), "size_gb": round(size / 1e9, 2)})
    return out, warnings


# ---------------------------------------------------------------------------
# building the nextflow command
# ---------------------------------------------------------------------------
def _coerce(v):
    lv = v.lower()
    if lv in ("true", "false"):
        return lv == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def parse_extra_params(text):
    """`key = value` (or `--key value`) per line, '#' starts a comment."""
    out, errors = {}, []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith(("'", '"')) else line.strip()
        if not line:
            continue
        m = re.match(r"^-{0,2}([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\s)\s*(.*)$", line)
        if not m:
            errors.append(f"line {n}: expected 'name = value': {line}")
            continue
        out[m.group(1)] = _coerce(m.group(2).strip())
    return out, errors


def profile_string(settings, test=False):
    if test:   # stub tasks only create placeholder files: no container images needed
        return "test"
    parts = []
    prof = settings.get("profile") or "docker"
    if prof != "none":
        parts.append(prof)
    if settings.get("gpu"):
        parts.append("gpu")
    if settings.get("slurm") and not test:
        parts.append("slurm")
    return ",".join(parts)


def build_params(settings, form):
    """params dict for -params-file. Run-form values win over settings."""
    test = bool(form.get("test"))
    p = {}
    if not test:
        # Nextflow runs inside the output folder, so every path must be absolute
        p["input"] = ",".join(os.path.abspath(os.path.expanduser(x.strip()))
                              for x in form.get("paths", []) if x.strip())
        p["group_by"] = form.get("group_by") or "folder"
        tools = [t for t in form.get("tools", []) if t in ALL_TOOLS]
        p["tools"] = ",".join(tools)
        for key in ("hg19_fasta", "hg38_fasta", "chm13_fasta", "assets_dir"):
            v = (settings.get(key) or "").strip()
            if v:
                p[key] = os.path.expanduser(v)
    if form.get("patient_id", "").strip():
        p["patient_id"] = form["patient_id"].strip()
    p["outdir"] = form["outdir"]
    for key in ("container_registry", "restricted_registry", "max_memory"):
        v = (settings.get(key) or "").strip()
        if v:
            p[key] = v
    if str(settings.get("max_cpus") or "").strip():
        p["max_cpus"] = _coerce(str(settings["max_cpus"]).strip())
    errors = []
    for text in (settings.get("extra_params", ""), form.get("extra_params", "")):
        extra, errs = parse_extra_params(text)
        p.update(extra)
        errors += errs
    if test:   # keep the test profile's own inputs/references
        for k in ("input", "hg19_fasta", "hg38_fasta", "chm13_fasta", "assets_dir", "lamprey_model"):
            p.pop(k, None)
    return p, errors


def build_command(settings, form, params_file):
    test = bool(form.get("test"))
    cmd = [nextflow_bin(settings), "run", MAIN_NF, "-ansi-log", "false",
           "-params-file", params_file]
    prof = profile_string(settings, test)
    if prof:
        cmd += ["-profile", prof]
    if settings.get("config_file"):
        cmd += ["-c", os.path.expanduser(settings["config_file"])]
    if form.get("resume"):
        cmd.append("-resume")
    if test or form.get("stub"):
        cmd.append("-stub-run")
    return cmd


def shell_join(cmd):
    import shlex
    return " ".join(shlex.quote(c) for c in cmd)


def default_outdir(settings, form):
    root = os.path.expanduser(settings.get("runs_root") or DEFAULT_SETTINGS["runs_root"])
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    if form.get("test"):
        label = "installation-test"
    else:
        paths = [x for x in form.get("paths", []) if x.strip()]
        label = os.path.basename(os.path.normpath(paths[0])) if paths else "run"
        if label.lower() in ("bam_pass", "pass", "bam"):
            label = os.path.basename(os.path.dirname(os.path.normpath(paths[0]))) or label
        label = re.sub(r"[^A-Za-z0-9._-]+", "_", _stem(label))[:60] or "run"
    return os.path.join(root, f"{stamp}_{label}")


# ---------------------------------------------------------------------------
# checks (the "Check setup" button)
# ---------------------------------------------------------------------------
def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, text=True)
        return r.returncode, r.stdout.strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as e:
        return 1, str(e)


def run_checks(settings, form):
    res = []

    def add(name, ok, detail="", level=None):
        res.append({"name": name, "status": level or ("ok" if ok else "error"), "detail": detail})

    test = bool(form.get("test"))
    tools = ALL_TOOLS if test else [t for t in form.get("tools", []) if t in ALL_TOOLS]

    nf = nextflow_bin(settings)
    code, out = _run([nf, "-version"], timeout=120)
    ver = re.search(r"version\s+([\d.]+)", out or "")
    add("Nextflow", code == 0, f"{nf}  ({'version ' + ver.group(1) if ver else out[-200:]})"
        if code == 0 else f"{nf}: {out[-300:]}. Install Nextflow or set its path in Settings.")
    java = shutil.which("java")
    if java:
        _, jout = _run(["java", "-version"])
        add("Java", True, (jout.splitlines() or [""])[0])
    else:
        add("Java", False, "java not on PATH (Nextflow needs Java 17+). "
            "Fine if the Nextflow check above passed with a bundled JVM.", level="warn")

    prof = settings.get("profile") or "docker"
    engine = prof if prof in CONTAINER_PROFILES else ("docker" if prof == "host" else None)
    if engine in ("docker", "podman"):
        code, out = _run([engine, "info", "--format", "{{.ServerVersion}}"])
        add(engine.capitalize(), code == 0, ("server " + out) if code == 0 else
            out[-300:] + (" (is your user in the 'docker' group?)" if engine == "docker" else ""))
        if code == 0 and prof != "host":
            tag = "1.0.0"
            restricted = settings.get("restricted_registry") or "methylclass"
            public = settings.get("container_registry") or "ghcr.io/rsankowski"
            for t in sorted(set(tools) & RESTRICTED_IMAGES):
                img = f"{restricted}/{t}:{tag}"
                c, _ = _run([engine, "image", "inspect", img])
                add(f"Image {img}", c == 0, "present" if c == 0 else
                    f"missing: build it with  containers/build.sh {t}")
            for t in ("hts", "align", "report"):
                img = f"{public}/{t}:{tag}"
                c, _ = _run([engine, "image", "inspect", img])
                add(f"Image {img}", True, "present" if c == 0 else
                    "not pulled yet (Nextflow pulls it on first use)", level=None if c == 0 else "warn")
    elif engine in ("singularity", "apptainer"):
        exe = shutil.which(engine)
        add(engine.capitalize(), bool(exe), exe or f"{engine} not on PATH")

    if test:
        add("Installation test", True, "uses the dummy data in tests/data (no references or models needed)")
        return res

    genomes = sorted({TOOL_GENOME[t] for t in tools if t in TOOL_GENOME})
    for g in genomes:
        fa = os.path.expanduser(settings.get(f"{g}_fasta") or "")
        if not fa:
            add(f"{g} FASTA", prof == "host", "not set in Settings" +
                (" (taken from conf/host.config)" if prof == "host" else ""),
                level="warn" if prof == "host" else None)
        elif not os.path.isfile(fa):
            add(f"{g} FASTA", False, "not found: " + fa)
        else:
            add(f"{g} FASTA", True, fa + ("" if os.path.isfile(fa + ".fai")
                                         else "  (no .fai yet: the pipeline creates one)"))

    extra, _ = parse_extra_params(settings.get("extra_params", "") + "\n" + form.get("extra_params", ""))
    assets = os.path.expanduser(settings.get("assets_dir") or "")
    for t in tools:
        for param, rel in TOOL_ASSETS.get(t, []):
            path = extra.get(param) or (os.path.join(assets, rel) if assets else "")
            if not path:
                add(f"{t}: {rel.split('/', 1)[1]}", prof == "host",
                    "set the Models folder (section 2)" if prof != "host" else "taken from conf/host.config",
                    level="warn" if prof == "host" else None)
            elif os.path.exists(os.path.expanduser(str(path))):
                add(f"{t}: {rel.split('/', 1)[1]}", True, str(path))
            elif t == "lamprey" and "/" in str(path) and not str(path).startswith(("/", "~", ".")):
                add("lamprey model", True, f"{path} (HuggingFace repo id: downloaded at run time)", level="warn")
            else:
                add(f"{t}: {rel.split('/', 1)[1]}", False, "not found: " + str(path) +
                    "  (scripts/download_assets.sh fills the assets folder)")
    if "rapidcns2" in tools or "metagenomics" in tools:
        add("Nested pipelines", True, "rapidCNS2 / metagenomics run nested Nextflow on this machine; "
            "rapidCNS2 also needs annovar/AnnotSV params (Advanced parameters)", level="warn")
    return res


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie child of ours counts as finished
    try:
        with open(f"/proc/{int(pid)}/stat") as fh:
            if fh.read().split(")")[-1].split()[0] == "Z":
                os.waitpid(int(pid), os.WNOHANG)
                return False
    except (OSError, IndexError, ChildProcessError):
        pass
    return True


def _state_dir(outdir):
    return os.path.join(outdir, STATE_NAME)


def run_status(entry):
    sd = _state_dir(entry["outdir"])
    try:
        with open(os.path.join(sd, "exitcode")) as fh:
            code = int(fh.read().strip() or "1")
        if os.path.exists(os.path.join(sd, "canceled")):
            return "canceled", code
        return ("done" if code == 0 else "failed"), code
    except (OSError, ValueError):
        pass
    if _pid_alive(entry.get("wrapper_pid")) or _pid_alive(_read_pid(sd)):
        return "running", None
    if os.path.exists(os.path.join(sd, "canceled")):
        return "canceled", None
    return "interrupted", None


def _read_pid(sd):
    try:
        with open(os.path.join(sd, "nextflow.pid")) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


WRAPPER = r'''
sd="$1"; shift
"$@" &
nf=$!
echo "$nf" > "$sd/nextflow.pid"
wait "$nf"
code=$?
echo "$code" > "$sd/exitcode"
if [ "$code" = 0 ] && [ -f "$sd/cleanup" ] && [ -d work ]; then
  echo "[gui] removing work/ (cleanup after success was ticked)"
  rm -rf work
fi
exit "$code"
'''


def start_run(settings, form):
    form = dict(form)
    outdir = (form.get("outdir") or "").strip()
    outdir = os.path.abspath(os.path.expanduser(outdir)) if outdir else default_outdir(settings, form)
    form["outdir"] = outdir

    if not form.get("test"):
        if not any(x.strip() for x in form.get("paths", [])):
            return None, "Add at least one input (BAM file, folder or sample,bam CSV)."
        if not [t for t in form.get("tools", []) if t in ALL_TOOLS]:
            return None, "Tick at least one tool."
        samples, _ = discover_samples(form.get("paths", []), form.get("group_by", "folder"))
        if not samples:
            return None, "No .bam files found in the inputs."
    for entry in load_history():
        if entry["outdir"] == outdir and run_status(entry)[0] == "running":
            return None, "A run is already active in " + outdir

    params, errors = build_params(settings, form)
    if errors:
        return None, "Advanced parameters: " + "; ".join(errors)

    os.makedirs(outdir, exist_ok=True)
    sd = _state_dir(outdir)
    os.makedirs(sd, exist_ok=True)
    for f in ("exitcode", "canceled", "nextflow.pid", "cleanup"):
        try:
            os.remove(os.path.join(sd, f))
        except OSError:
            pass
    if form.get("cleanup"):
        open(os.path.join(sd, "cleanup"), "w").close()
    params_file = os.path.join(sd, "params.json")
    _write_json(params_file, params)
    cmd = build_command(settings, form, params_file)

    log_path = os.path.join(outdir, LOG_NAME)
    env = dict(os.environ, NXF_ANSI_LOG="false")
    nf = cmd[0]
    if os.path.sep in nf:   # nested pipelines call `nextflow` too
        env["PATH"] = os.path.dirname(nf) + os.pathsep + env.get("PATH", "")
    with open(log_path, "a") as log:
        log.write(f"\n[gui] {datetime.now():%Y-%m-%d %H:%M:%S}  starting in {outdir}\n")
        log.write("[gui] $ " + shell_join(cmd) + "\n[gui] params: " + json.dumps(params) + "\n\n")
        log.flush()
        try:
            proc = subprocess.Popen(["/bin/sh", "-c", WRAPPER, "fr-methylclass-run", sd] + cmd,
                                    cwd=outdir, stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        except OSError as e:
            return None, f"Could not start Nextflow: {e}"
    threading.Thread(target=proc.wait, daemon=True).start()   # reap the wrapper

    entry = {
        "id": uuid.uuid4().hex[:10],
        "outdir": outdir,
        "started": datetime.now().isoformat(timespec="seconds"),
        "started_ts": time.time(),
        "wrapper_pid": proc.pid,
        "command": shell_join(cmd),
        "tools": params.get("tools", "all (test)"),
        "inputs": form.get("paths", []),
        "test": bool(form.get("test")),
        "label": os.path.basename(outdir),
    }
    with LOCK:
        h = [e for e in load_history() if e["outdir"] != outdir]
        h.insert(0, entry)
        save_history(h[:200])
    return entry, None


def cancel_run(entry):
    sd = _state_dir(entry["outdir"])
    open(os.path.join(sd, "canceled"), "w").close()
    pid = _read_pid(sd)
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)   # Nextflow stops its tasks on SIGTERM
        except OSError:
            pass

        def hard_kill():
            time.sleep(60)
            if _pid_alive(pid):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except OSError:
                    pass
        threading.Thread(target=hard_kill, daemon=True).start()
        return True
    return False


# Nextflow < 25: "[ab/cdef12] Submitted process > NAME (tag)"; >= 25: "[PROCESS ab/cdef12] NAME (tag)"
TASK_RE = re.compile(r"^\[([0-9a-f]{2}/[0-9a-f]{6})\]\s+(Submitted|Cached|Re-submitted)\s+process\s+>\s+(.+?)\s*$")
TASK_RE_NEW = re.compile(r"^\[PROCESS\s+([0-9a-f]{2}/[0-9a-f]{6})\]\s+(.+?)\s*$")


def read_tasks(entry):
    """Tasks from the stdout log (submitted/cached) and the trace file (finished)."""
    outdir = entry["outdir"]
    tasks = {}
    log_path = os.path.join(outdir, LOG_NAME)
    started_marker = entry.get("started_ts", 0)
    try:
        with open(log_path, errors="replace") as fh:
            lines = fh.read().splitlines()
        # only the latest GUI start in this folder
        last = max((i for i, l in enumerate(lines) if l.startswith("[gui] ") and "starting in" in l), default=0)
        for l in lines[last:]:
            m = TASK_RE.match(l)
            if m:
                h, kind, name = m.groups()
            else:
                m = TASK_RE_NEW.match(l)
                if not m:
                    continue
                h, name = m.groups()
                kind = "Cached" if re.search(r"\bcached\b", name, re.I) else "Submitted"
                name = re.sub(r"\s*\[?\(?cached\)?\]?\s*$", "", name, flags=re.I)
            tasks[h] = {"hash": h, "name": name,
                        "status": "CACHED" if kind == "Cached" else "RUNNING"}
    except OSError:
        pass
    info = os.path.join(outdir, "pipeline_info")
    traces = []
    try:
        for f in os.listdir(info):
            if f.startswith("trace_") and f.endswith(".txt"):
                p = os.path.join(info, f)
                if os.path.getmtime(p) >= started_marker - 5:
                    traces.append(p)
    except OSError:
        pass
    for p in sorted(traces):
        try:
            with open(p, errors="replace") as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
        except OSError:
            continue
        for r in rows:
            h = r.get("hash")
            if not h:
                continue
            t = tasks.setdefault(h, {"hash": h, "name": r.get("name", "?")})
            t["status"] = r.get("status", t.get("status", "?"))
            t["duration"] = r.get("duration", "")
            t["exit"] = r.get("exit", "")
    order = {"RUNNING": 0, "FAILED": 1, "ABORTED": 2, "COMPLETED": 3, "CACHED": 4}
    out = sorted(tasks.values(), key=lambda t: (order.get(t.get("status"), 5), t["name"]))
    counts = {}
    for t in out:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return out, counts


def list_results(entry):
    outdir = entry["outdir"]
    groups = []

    def collect(title, rel_dir, pattern, recursive=False):
        base = os.path.join(outdir, rel_dir)
        found = []
        if os.path.isdir(base):
            walker = os.walk(base) if recursive else [(base, [], os.listdir(base))]
            for root, _, files in walker:
                for f in sorted(files):
                    if re.search(pattern, f):
                        found.append(os.path.relpath(os.path.join(root, f), outdir))
        if found:
            groups.append({"title": title, "files": sorted(found)})

    collect("PDF reports", "report", r"\.pdf$")
    collect("crossNN", "crossnn/results", r"_top\.tsv$")
    collect("MethyLYZR", "methylyzr/results", r"\.(pdf|csv)$")
    collect("Sturgeon V2", "sturgeon/results", r"(_scores\.tsv|\.png)$", recursive=True)
    collect("Lamprey", "lamprey/results", r"(_report\.txt|\.png)$")
    collect("Copy number", "cnv", r"\.png$")
    collect("Nextflow run reports", "pipeline_info", r"^(report|timeline)_.*\.html$")
    return groups


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "fr-methylclass-gui/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, download=False):
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        disp = "attachment" if download else "inline"
        self.send_header("Content-Disposition", f'{disp}; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile)

    def _send_logo(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        ctype = ("image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else
                 "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/svg+xml")
        self._send(200, data, ctype)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return {}

    def _local_only(self):
        # refuse cross-site requests: only our own page may call the API
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and urllib.parse.urlparse(origin).netloc != host:
            self._send(403, {"error": "cross-origin request refused"})
            return False
        return True

    def _entry(self, rid):
        for e in load_history():
            if e["id"] == rid:
                return e
        return None

    def _snapshot(self, e, full=False):
        status, code = run_status(e)
        d = dict(e, status=status, exit_code=code)
        if full:
            d["tasks"], d["counts"] = read_tasks(e)
            d["results"] = list_results(e)
        return d

    # ---- GET ---------------------------------------------------------------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        q = lambda k, d="": (qs.get(k) or [d])[0]
        path = u.path
        if path in ("/", "/index.html"):
            return self._send_file(os.path.join(STATIC_DIR, "index.html"))
        if path.startswith("/static/"):
            f = os.path.normpath(os.path.join(STATIC_DIR, path[len("/static/"):]))
            if not f.startswith(STATIC_DIR + os.sep):
                return self._send(404, {"error": "not found"})
            return self._send_file(f)
        if path == "/api/logo":
            # an institutional logo is not shipped; drop logo.png/.svg/.jpg into gui/assets/
            for name in ("logo.png", "logo.svg", "logo.jpg", "freiburg_logo.png", "freiburg_logo.svg"):
                f = os.path.join(GUI_DIR, "assets", name)
                if os.path.isfile(f):
                    return self._send_logo(f)
            return self._send_file(os.path.join(STATIC_DIR, "icon.svg"))
        if path == "/favicon.ico":
            return self._send_file(os.path.join(STATIC_DIR, "icon.svg"))
        if path == "/api/settings":
            return self._send(200, {"settings": load_settings(), "repo": REPO_DIR,
                                    "tools": ALL_TOOLS, "nextflow": nextflow_bin(load_settings())})
        if path == "/api/browse":
            return self.api_browse(q("path"), q("mode", "bam"))
        if path == "/api/runs":
            return self._send(200, [self._snapshot(e) for e in load_history()])
        if path.startswith("/api/run/"):
            e = self._entry(path.rsplit("/", 1)[-1])
            return self._send(200, self._snapshot(e, full=True)) if e else self._send(404, {"error": "unknown run"})
        if path.startswith("/api/log/"):
            e = self._entry(path.rsplit("/", 1)[-1])
            if not e:
                return self._send(404, {"error": "unknown run"})
            return self.api_log(e, int(q("offset", "0") or 0))
        if path.startswith("/api/file/"):
            e = self._entry(path.split("/")[3])
            if not e:
                return self._send(404, {"error": "unknown run"})
            root = os.path.realpath(e["outdir"])
            f = os.path.realpath(os.path.join(root, q("rel")))
            if not f.startswith(root + os.sep):
                return self._send(403, {"error": "outside the run folder"})
            return self._send_file(f, download=q("download") == "1")
        return self._send(404, {"error": "not found"})

    def api_browse(self, raw, mode):
        path = os.path.abspath(os.path.expanduser(raw or "~"))
        while not os.path.isdir(path) and path != os.path.dirname(path):
            path = os.path.dirname(path)
        exts = {"bam": (".bam", ".csv"), "fasta": (".fa", ".fasta", ".fna", ".fa.gz", ".fasta.gz"),
                "config": (".config",), "file": None, "dir": ()}.get(mode, ())
        entries = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    if e.name.startswith("."):
                        continue
                    try:
                        is_dir = e.is_dir()
                    except OSError:
                        continue
                    if not is_dir and (exts == () or (exts and not e.name.lower().endswith(exts))):
                        continue
                    entries.append({"name": e.name, "path": os.path.join(path, e.name), "dir": is_dir})
        except PermissionError:
            return self._send(403, {"error": "permission denied: " + path})
        entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
        parent = os.path.dirname(path)
        return self._send(200, {"path": path, "parent": parent if parent != path else None,
                                "entries": entries, "home": os.path.expanduser("~")})

    def api_log(self, e, offset):
        p = os.path.join(e["outdir"], LOG_NAME)
        try:
            size = os.path.getsize(p)
            if offset > size:
                offset = 0
            start = offset if offset else max(0, size - 400_000)
            with open(p, "rb") as fh:
                fh.seek(start)
                data = fh.read(2_000_000)
            return self._send(200, {"text": data.decode("utf-8", "replace"),
                                    "offset": start + len(data), "truncated": start > offset})
        except OSError:
            return self._send(200, {"text": "", "offset": 0})

    # ---- POST --------------------------------------------------------------
    def do_POST(self):
        if not self._local_only():
            return
        path = urllib.parse.urlparse(self.path).path
        body = self._body()
        if path == "/api/settings":
            return self._send(200, {"settings": save_settings(body)})
        if path == "/api/discover":
            samples, warnings = discover_samples(body.get("paths", []), body.get("group_by", "folder"))
            return self._send(200, {"samples": samples, "warnings": warnings,
                                    "n_bams": sum(s["n_bams"] for s in samples),
                                    "size_gb": round(sum(s["size_gb"] for s in samples), 2)})
        if path == "/api/preview":
            s = load_settings()
            form = dict(body)
            form["outdir"] = os.path.abspath(os.path.expanduser(form["outdir"])) \
                if form.get("outdir", "").strip() else default_outdir(s, form)
            params, errors = build_params(s, form)
            cmd = build_command(s, form, os.path.join(form["outdir"], STATE_NAME, "params.json"))
            return self._send(200, {"command": "cd " + shell_join([form["outdir"]]) + " && " + shell_join(cmd),
                                    "params": params, "errors": errors, "outdir": form["outdir"]})
        if path == "/api/check":
            return self._send(200, {"checks": run_checks(load_settings(), body)})
        if path == "/api/run":
            entry, err = start_run(load_settings(), body)
            return self._send(400, {"error": err}) if err else self._send(200, self._snapshot(entry))
        if path.startswith("/api/cancel/"):
            e = self._entry(path.rsplit("/", 1)[-1])
            if not e:
                return self._send(404, {"error": "unknown run"})
            return self._send(200, {"ok": cancel_run(e)})
        if path.startswith("/api/forget/"):
            rid = path.rsplit("/", 1)[-1]
            with LOCK:
                save_history([e for e in load_history() if e["id"] != rid])
            return self._send(200, {"ok": True})
        if path.startswith("/api/open/"):
            e = self._entry(path.rsplit("/", 1)[-1])
            if not e:
                return self._send(404, {"error": "unknown run"})
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            try:
                subprocess.Popen([opener, e["outdir"]], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return self._send(200, {"ok": True})
            except OSError as ex:
                return self._send(500, {"error": str(ex)})
        if path == "/api/quit":
            self._send(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        return self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser(description="fr-methylclass GUI")
    ap.add_argument("--port", type=int, default=int(os.environ.get("FR_METHYLCLASS_GUI_PORT", DEFAULT_PORT)))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError as e:
        print(f"Port {a.port} is busy ({e}). Is the GUI already running? Open http://127.0.0.1:{a.port}",
              file=sys.stderr)
        sys.exit(2)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{a.port}/"
    print(f"fr-methylclass GUI on {url}  (close it with the Quit button or Ctrl+C)", flush=True)
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("GUI stopped. Running pipelines keep running; reopen the GUI to follow them.")


if __name__ == "__main__":
    main()
