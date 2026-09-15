/**
 * Main UI Controller for mod-scanner Wasm WebApp
 */

(() => {
    // DOM Elements
    const initCard = document.getElementById("initCard");
    const initTitle = document.getElementById("initTitle");
    const initStatusText = document.getElementById("initStatusText");
    const initProgressBar = document.getElementById("initProgressBar");

    const mainSection = document.getElementById("mainSection");
    const dropzone = document.getElementById("dropzone");
    const fileZipInput = document.getElementById("fileZipInput");
    const folderInput = document.getElementById("folderInput");
    const inputRepoUrl = document.getElementById("inputRepoUrl");
    const btnScanUrl = document.getElementById("btnScanUrl");

    const btnSettings = document.getElementById("btnSettings");
    const settingsDrawer = document.getElementById("settingsDrawer");
    const btnCloseSettings = document.getElementById("btnCloseSettings");
    const inputGhToken = document.getElementById("inputGhToken");
    const inputAutoReject = document.getElementById("inputAutoReject");
    const inputFlagThreshold = document.getElementById("inputFlagThreshold");
    const inputWhitelist = document.getElementById("inputWhitelist");

    const scanningStatusCard = document.getElementById("scanningStatusCard");
    const scanStatusTitle = document.getElementById("scanStatusTitle");
    const scanStatusFile = document.getElementById("scanStatusFile");
    const scanPercentBadge = document.getElementById("scanPercentBadge");
    const scanProgressBar = document.getElementById("scanProgressBar");

    const resultsSection = document.getElementById("resultsSection");
    const statusBanner = document.getElementById("statusBanner");
    const statusIcon = document.getElementById("statusIcon");
    const statusTitle = document.getElementById("statusTitle");
    const statusBadge = document.getElementById("statusBadge");
    const statusSummary = document.getElementById("statusSummary");

    const metricFiles = document.getElementById("metricFiles");
    const metricTime = document.getElementById("metricTime");
    const metricViolations = document.getElementById("metricViolations");
    const metricFlags = document.getElementById("metricFlags");

    const violationsContainer = document.getElementById("violationsContainer");
    const violationsCount = document.getElementById("violationsCount");
    const violationsList = document.getElementById("violationsList");

    const flagsContainer = document.getElementById("flagsContainer");
    const flagsCount = document.getElementById("flagsCount");
    const flagsGallery = document.getElementById("flagsGallery");

    const btnExportMd = document.getElementById("btnExportMd");
    const btnExportJson = document.getElementById("btnExportJson");
    const btnScanAnother = document.getElementById("btnScanAnother");

    const imageModal = document.getElementById("imageModal");
    const modalImage = document.getElementById("modalImage");
    const modalImageTitle = document.getElementById("modalImageTitle");
    const btnCloseModal = document.getElementById("btnCloseModal");

    let worker = null;
    let latestScanResult = null;
    let isScanning = false;

    // ====================================================================
    // Web Worker Initialization
    // ====================================================================

    function initWorker() {
        worker = new Worker("worker.js");

        worker.onmessage = (e) => {
            const { type, step, totalSteps, message, current, total, filename, percentage, result, error } = e.data;

            switch (type) {
                case "INIT_PROGRESS":
                    initStatusText.textContent = message;
                    if (totalSteps > 0) {
                        const pct = Math.round((step / totalSteps) * 100);
                        initProgressBar.style.width = `${pct}%`;
                    }
                    break;

                case "READY":
                    initCard.style.display = "none";
                    mainSection.style.display = "block";
                    break;

                case "INIT_ERROR":
                    initTitle.textContent = "Engine Initialization Failed";
                    initStatusText.textContent = message;
                    initProgressBar.style.background = "var(--color-reject)";
                    break;

                case "PROGRESS":
                    scanPercentBadge.textContent = `${percentage}%`;
                    scanProgressBar.style.width = `${percentage}%`;
                    scanStatusFile.textContent = `${current}/${total}: ${filename}`;
                    break;

                case "SCAN_COMPLETE":
                    finishScan(result);
                    break;

                case "ERROR":
                    alert(`Scan Error: ${message || error}`);
                    resetScanState();
                    break;
            }
        };

        worker.onerror = (err) => {
            console.error("Worker Error:", err);
            alert("An unexpected Web Worker error occurred.");
            resetScanState();
        };

        worker.postMessage({ type: "INIT" });
    }

    // ====================================================================
    // UI Helpers & Tab Switching
    // ====================================================================

    function setupTabs() {
        const tabBtns = document.querySelectorAll(".tab-btn");
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                tabBtns.forEach(b => b.classList.remove("active"));
                document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
                btn.classList.add("active");
                const target = document.getElementById(btn.dataset.tab);
                if (target) target.classList.add("active");
            });
        });
    }

    function setupSettings() {
        btnSettings.addEventListener("click", () => {
            const isOpen = settingsDrawer.style.display === "block";
            settingsDrawer.style.display = isOpen ? "none" : "block";
        });
        btnCloseSettings.addEventListener("click", () => {
            settingsDrawer.style.display = "none";
        });
    }

    function getScanOptions() {
        return {
            autoRejectThreshold: parseInt(inputAutoReject.value) || 14,
            flagThreshold: parseInt(inputFlagThreshold.value) || 30,
        };
    }

    function getWhitelist() {
        const raw = inputWhitelist.value.trim();
        if (!raw) return [];
        return raw.split(/[\s,]+/).filter(Boolean);
    }

    // ====================================================================
    // Scan Execution & Buffer Transfer
    // ====================================================================

    function startScanUI(targetName) {
        isScanning = true;
        resultsSection.style.display = "none";
        scanningStatusCard.style.display = "flex";
        scanStatusTitle.textContent = `Scanning: ${targetName}`;
        scanStatusFile.textContent = "Initializing stream...";
        scanProgressBar.style.width = "0%";
        scanPercentBadge.textContent = "0%";
    }

    function resetScanState() {
        isScanning = false;
        scanningStatusCard.style.display = "none";
    }

    async function scanArrayBuffer(arrayBuffer, name) {
        startScanUI(name);

        const options = getScanOptions();
        const whitelist = getWhitelist();

        // Transfer arrayBuffer ownership directly to Web Worker with zero memory copy cost
        worker.postMessage({
            type: "SCAN_BUFFER",
            buffer: arrayBuffer,
            name: name,
            options: options,
            whitelist: whitelist,
        }, [arrayBuffer]);
    }

    // ====================================================================
    // Dropzone & File Handlers
    // ====================================================================

    function setupDropzone() {
        dropzone.addEventListener("click", () => fileZipInput.click());

        fileZipInput.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const buffer = await file.arrayBuffer();
            scanArrayBuffer(buffer, file.name);
            fileZipInput.value = "";
        });

        ["dragenter", "dragover"].forEach(evt => {
            dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add("dragover");
            });
        });

        ["dragleave", "drop"].forEach(evt => {
            dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove("dragover");
            });
        });

        dropzone.addEventListener("drop", async (e) => {
            const file = e.dataTransfer.files[0];
            if (!file) return;
            if (!file.name.toLowerCase().endsWith(".zip")) {
                alert("Please drop a .zip archive.");
                return;
            }
            const buffer = await file.arrayBuffer();
            scanArrayBuffer(buffer, file.name);
        });
    }

    function setupFolderPicker() {
        folderInput.addEventListener("change", async (e) => {
            const files = Array.from(e.target.files);
            if (files.length === 0) return;

            startScanUI("Packaging local folder...");
            scanStatusFile.textContent = `Reading ${files.length} files...`;

            try {
                // Pack directory into zip in memory using fflate
                const zipObj = {};
                for (const file of files) {
                    const relPath = file.webkitRelativePath || file.name;
                    const arr = new Uint8Array(await file.arrayBuffer());
                    zipObj[relPath] = arr;
                }

                scanStatusFile.textContent = "Compressing in-memory zip...";
                const zippedData = fflate.zipSync(zipObj);
                scanArrayBuffer(zippedData.buffer, "folder_upload.zip");
            } catch (err) {
                alert(`Failed to package folder: ${err.message}`);
                resetScanState();
            }

            folderInput.value = "";
        });
    }

    // ====================================================================
    // GitHub Repo & URL Fetcher
    // ====================================================================

    function parseGitHubUrl(urlStr) {
        try {
            const parsed = new URL(urlStr.trim());
            if (parsed.hostname !== "github.com") return null;

            const segments = parsed.pathname.replace(/^\/+|\/+$/g, "").split("/");
            if (segments.length >= 2) {
                const owner = segments[0];
                const repo = segments[1];
                let ref = "main";
                if (segments.length >= 4 && segments[2] === "tree") {
                    ref = segments.slice(3).join("/");
                }
                return { owner, repo, ref };
            }
        } catch (_) {}
        return null;
    }

    async function handleGitHubScan() {
        const url = inputRepoUrl.value.trim();
        if (!url) {
            alert("Please enter a GitHub repository or release URL.");
            return;
        }

        const ghInfo = parseGitHubUrl(url);
        startScanUI(url);
        scanStatusFile.textContent = "Fetching archive stream from GitHub...";

        const token = inputGhToken.value.trim();
        const headers = {};
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        try {
            let downloadUrl = url;
            let archiveName = "remote_mod.zip";

            if (ghInfo) {
                // Use GitHub API to download zipball (CORS-enabled)
                downloadUrl = `https://api.github.com/repos/${ghInfo.owner}/${ghInfo.repo}/zipball/${ghInfo.ref}`;
                archiveName = `${ghInfo.owner}_${ghInfo.repo}.zip`;
            }

            const response = await fetch(downloadUrl, { headers });

            if (response.status === 403) {
                throw new Error("GitHub API rate limit exceeded (60 requests/hr). Please add a Personal Access Token in Settings or drag-and-drop the downloaded .zip directly.");
            }
            if (response.status === 404 && ghInfo && ghInfo.ref === "main") {
                // Retry with 'master' branch fallback
                const altUrl = `https://api.github.com/repos/${ghInfo.owner}/${ghInfo.repo}/zipball/master`;
                const altResp = await fetch(altUrl, { headers });
                if (!altResp.ok) throw new Error(`Failed to fetch repo: ${altResp.statusText}`);
                const buffer = await altResp.arrayBuffer();
                scanArrayBuffer(buffer, archiveName);
                return;
            }
            if (!response.ok) {
                throw new Error(`Failed to download URL (HTTP ${response.status}: ${response.statusText}). If CORS is blocked, please download the file and drag-and-drop it.`);
            }

            const buffer = await response.arrayBuffer();
            scanArrayBuffer(buffer, archiveName);

        } catch (err) {
            alert(`Download Error: ${err.message}`);
            resetScanState();
        }
    }

    function setupUrlScanner() {
        btnScanUrl.addEventListener("click", handleGitHubScan);
        inputRepoUrl.addEventListener("keydown", (e) => {
            if (e.key === "Enter") handleGitHubScan();
        });
    }

    // ====================================================================
    // Results Presentation
    // ====================================================================

    function finishScan(result) {
        latestScanResult = result;
        resetScanState();

        // Metrics
        metricFiles.textContent = result.scanned_file_count;
        metricTime.textContent = `${result.elapsed_seconds}s`;
        metricViolations.textContent = result.violations.length;
        metricFlags.textContent = result.flags.length;

        // Banner styling
        statusBanner.className = "status-banner";
        if (result.status === "CLEAN") {
            statusBanner.classList.add("banner-clean");
            statusIcon.textContent = "✓";
            statusTitle.textContent = "PASSED (CLEAN)";
            statusBadge.textContent = "CLEAN";
            statusSummary.textContent = "Passed all checks. Ready for release distribution.";
        } else if (result.status === "FLAGGED") {
            statusBanner.classList.add("banner-flagged");
            statusIcon.textContent = "!";
            statusTitle.textContent = "FLAGGED (REVIEW REQUIRED)";
            statusBadge.textContent = "FLAGGED";
            statusSummary.textContent = "High visual similarity to canonical sprites detected. Review 3-panel diffs below.";
        } else {
            statusBanner.classList.add("banner-reject");
            statusIcon.textContent = "✕";
            statusTitle.textContent = "REJECTED (PROHIBITED)";
            statusBadge.textContent = "REJECT";
            statusSummary.textContent = "Prohibited ROM headers, containers, or direct rips detected.";
        }

        // Render Violations
        if (result.violations && result.violations.length > 0) {
            violationsContainer.style.display = "block";
            violationsCount.textContent = result.violations.length;
            violationsList.innerHTML = result.violations.map(v => `
                <div class="violation-item">
                    <div class="violation-title">
                        <span>[${escapeHtml(v.rule_type)}]</span>
                        <span class="violation-path">${escapeHtml(v.file_path)}</span>
                    </div>
                    <p class="violation-reason">${escapeHtml(v.message)}</p>
                </div>
            `).join("");
        } else {
            violationsContainer.style.display = "none";
        }

        // Render Flags (3-Panel Diffs)
        if (result.flags && result.flags.length > 0) {
            flagsContainer.style.display = "block";
            flagsCount.textContent = result.flags.length;
            flagsGallery.innerHTML = result.flags.map((f, i) => `
                <div class="flag-card">
                    <div class="flag-header">
                        <span class="flag-path">${escapeHtml(f.file_path)}</span>
                        <span class="flag-score-badge">Dist: ${f.hamming_distance}/256 (${f.similarity_pct})</span>
                    </div>
                    <div class="flag-image-box" onclick="window.openDiffModal('${i}')">
                        ${f.preview_data_url ? `<img src="${f.preview_data_url}" alt="3-Panel Diff for ${escapeHtml(f.file_path)}">` : '<span class="text-muted">Diff preview unavailable</span>'}
                    </div>
                    <div class="flag-footer">
                        <span>Matched: <code>${escapeHtml(f.matched_ref)}</code></span>
                        <span>Click image to zoom</span>
                    </div>
                </div>
            `).join("");
        } else {
            flagsContainer.style.display = "none";
        }

        resultsSection.style.display = "flex";
        resultsSection.scrollIntoView({ behavior: "smooth" });
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // ====================================================================
    // Image Modal Lightbox
    // ====================================================================

    window.openDiffModal = function(flagIndex) {
        if (!latestScanResult || !latestScanResult.flags) return;
        const flag = latestScanResult.flags[flagIndex];
        if (!flag || !flag.preview_data_url) return;

        modalImageTitle.textContent = `Diff Preview: ${flag.file_path} (vs ${flag.matched_ref})`;
        modalImage.src = flag.preview_data_url;
        imageModal.style.display = "flex";
    };

    btnCloseModal.addEventListener("click", () => imageModal.style.display = "none");
    imageModal.addEventListener("click", (e) => {
        if (e.target === imageModal) imageModal.style.display = "none";
    });

    // ====================================================================
    // Report Exports
    // ====================================================================

    function downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    btnExportMd.addEventListener("click", () => {
        if (!latestScanResult) return;
        const r = latestScanResult;
        let md = `# mod-scanner Verification Report\n\n`;
        md += `**Target Archive:** \`${r.archive_name}\`\n`;
        md += `**Status:** \`${r.status}\`\n`;
        md += `**Files Scanned:** ${r.scanned_file_count}\n`;
        md += `**Elapsed Time:** ${r.elapsed_seconds}s\n\n`;
        md += `### Summary\n${r.summary}\n\n`;

        if (r.violations.length > 0) {
            md += `### Prohibited Violations (${r.violations.length})\n`;
            r.violations.forEach(v => {
                md += `- **[${v.rule_type}]** \`${v.file_path}\`: ${v.message}\n`;
            });
            md += `\n`;
        }

        if (r.flags.length > 0) {
            md += `### Similarity Flags (${r.flags.length})\n`;
            r.flags.forEach(f => {
                md += `- **\`${f.file_path}\`**: Matched \`${f.matched_ref}\` (Hamming Distance: ${f.hamming_distance}/256, ${f.similarity_pct} similarity)\n`;
            });
            md += `\n`;
        }

        downloadFile(md, `mod-scan-report-${Date.now()}.md`, "text/markdown");
    });

    btnExportJson.addEventListener("click", () => {
        if (!latestScanResult) return;
        const jsonStr = JSON.stringify(latestScanResult, null, 2);
        downloadFile(jsonStr, `mod-scan-report-${Date.now()}.json`, "application/json");
    });

    btnScanAnother.addEventListener("click", () => {
        resultsSection.style.display = "none";
        window.scrollTo({ top: 0, behavior: "smooth" });
    });

    // ====================================================================
    // Boot Initialization
    // ====================================================================

    setupTabs();
    setupSettings();
    setupDropzone();
    setupFolderPicker();
    setupUrlScanner();
    initWorker();

})();
