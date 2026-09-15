/**
 * Dedicated Web Worker for Pyodide Mod Scanner
 * Runs all WebAssembly execution and CPU-intensive hashing off the main UI thread.
 */

// Import official Pyodide WebAssembly runtime from CDN
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let pyodide = null;
let isReady = false;

// Global proxies for Python async calls
self.imageFetcherProxy = async (url) => {
    try {
        const res = await fetch(url);
        if (!res.ok) return null;
        const arrayBuf = await res.arrayBuffer();
        return new Uint8Array(arrayBuf);
    } catch (err) {
        console.warn("Failed to fetch reference sprite:", url, err);
        return null;
    }
};

self.progressProxy = (current, total, filename) => {
    self.postMessage({
        type: "PROGRESS",
        current,
        total,
        filename: String(filename),
        percentage: total > 0 ? Math.round((current / total) * 100) : 0
    });
};

async function initPyodideScanner() {
    try {
        self.postMessage({
            type: "INIT_PROGRESS",
            step: 1,
            totalSteps: 4,
            message: "Downloading WebAssembly Python runtime..."
        });

        pyodide = await loadPyodide({
            indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"
        });

        self.postMessage({
            type: "INIT_PROGRESS",
            step: 2,
            totalSteps: 4,
            message: "Loading Pillow & YAML engines..."
        });

        await pyodide.loadPackage(["pillow", "pyyaml"]);

        self.postMessage({
            type: "INIT_PROGRESS",
            step: 3,
            totalSteps: 4,
            message: "Fetching reference hashes and scan rules..."
        });

        const [configRes, refRes, codeRes] = await Promise.all([
            fetch("./config.yaml").then(r => r.text()),
            fetch("./reference_hashes.json").then(r => r.text()),
            fetch("./pyodide_scanner.py").then(r => r.text())
        ]);

        self.postMessage({
            type: "INIT_PROGRESS",
            step: 4,
            totalSteps: 4,
            message: "Compiling scan engine & mounting databases..."
        });

        // Load python scanner code and instantiate WebModScanner
        self.rawConfigYaml = configRes;
        self.rawRefHashesJson = refRes;

        pyodide.runPython(codeRes);
        pyodide.runPython(`
import js
scanner = WebModScanner(
    config_yaml_str=js.rawConfigYaml,
    reference_hashes_json_str=js.rawRefHashesJson
)
`);

        isReady = true;
        self.postMessage({ type: "READY" });

    } catch (err) {
        self.postMessage({
            type: "INIT_ERROR",
            message: err.message || String(err)
        });
    }
}

self.onmessage = async (e) => {
    const { type, buffer, name, options, whitelist } = e.data;

    if (type === "INIT") {
        if (!isReady && !pyodide) {
            await initPyodideScanner();
        } else if (isReady) {
            self.postMessage({ type: "READY" });
        }
        return;
    }

    if (type === "SCAN_BUFFER") {
        if (!isReady) {
            self.postMessage({
                type: "ERROR",
                message: "Scanner engine is still initializing, please wait a moment."
            });
            return;
        }

        try {
            self.currentScanBuffer = new Uint8Array(buffer);
            self.currentScanName = name || "mod.zip";

            if (whitelist && Array.isArray(whitelist) && whitelist.length > 0) {
                self.customWhitelist = whitelist;
                pyodide.runPython(`
import js
scanner.add_whitelist_hashes(list(js.customWhitelist))
`);
            }

            if (options && options.autoRejectThreshold !== undefined) {
                pyodide.runPython(`
scanner.image_rules.threshold_auto_reject = ${parseInt(options.autoRejectThreshold)}
scanner.image_rules.threshold_flag_for_review = ${parseInt(options.flagThreshold)}
`);
            }

            const jsonResultStr = await pyodide.runPythonAsync(`
import js
import json

async def _execute_scan():
    async def _fetch_proxy(url):
        buf = await js.imageFetcherProxy(url)
        if buf is None:
            return None
        return bytes(buf.to_py())

    def _prog_proxy(c, t, fn):
        js.progressProxy(c, t, fn)

    raw_bytes = bytes(js.currentScanBuffer.to_py())
    res = await scanner.scan_zip(
        zip_bytes=raw_bytes,
        archive_name=str(js.currentScanName),
        progress_callback=_prog_proxy,
        image_fetcher=_fetch_proxy
    )
    return res

res = await _execute_scan()
json.dumps(res)
`);

            // Clean up buffer references to release memory immediately
            self.currentScanBuffer = null;

            const scanResult = JSON.parse(jsonResultStr);
            self.postMessage({
                type: "SCAN_COMPLETE",
                result: scanResult
            });

        } catch (err) {
            self.currentScanBuffer = null;
            self.postMessage({
                type: "ERROR",
                message: err.message || String(err)
            });
        }
    }
};

// Start initial loading automatically
initPyodideScanner();
