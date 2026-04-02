/* ============================================================
   MoncifEdits AI — Frontend JavaScript
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

    // ── State ──
    let selectedPreset = 'funk_bounce';
    let selectedQuality = 'hd';
    let videoFile = null;
    let audioFile = null;

    // ── Elements ──
    const videoUpload = document.getElementById('videoUpload');
    const audioUpload = document.getElementById('audioUpload');
    const videoZone = document.getElementById('videoZone');
    const audioZone = document.getElementById('audioZone');
    const renderBtn = document.getElementById('renderBtn');
    const progressSection = document.getElementById('renderProgress');
    const outputSection = document.getElementById('outputSection');
    const intensitySlider = document.getElementById('intensitySlider');
    const intensityValue = document.getElementById('intensityValue');
    const projectName = document.getElementById('projectName');

    // ── Particles ──
    createParticles();

    // ── Scroll Reveal ──
    initScrollReveal();

    // ── Upload Zones ──
    setupUploadZone(videoZone, videoUpload, 'video');
    setupUploadZone(audioZone, audioUpload, 'audio');

    // ── Preset Selection ──
    document.querySelectorAll('.preset-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            selectedPreset = card.dataset.preset;
        });
    });

    // Set default active preset
    const defaultPreset = document.querySelector(`[data-preset="${selectedPreset}"]`);
    if (defaultPreset) defaultPreset.classList.add('active');

    // ── Quality Toggle ──
    document.querySelectorAll('.quality-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedQuality = btn.dataset.quality;
        });
    });

    // ── Intensity Slider ──
    if (intensitySlider) {
        intensitySlider.addEventListener('input', (e) => {
            intensityValue.textContent = parseFloat(e.target.value).toFixed(1) + 'x';
        });
    }

    // ── Render Button ──
    renderBtn.addEventListener('click', startRender);

    // ── Smooth scroll for CTA ──
    const ctaBtn = document.querySelector('.hero-cta');
    if (ctaBtn) {
        ctaBtn.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('editor').scrollIntoView({ behavior: 'smooth' });
        });
    }


    // ────────────────────────────────────────────
    // FUNCTIONS
    // ────────────────────────────────────────────

    function createParticles() {
        const container = document.querySelector('.particles');
        if (!container) return;
        for (let i = 0; i < 30; i++) {
            const p = document.createElement('div');
            p.classList.add('particle');
            p.style.left = Math.random() * 100 + '%';
            p.style.animationDelay = Math.random() * 8 + 's';
            p.style.animationDuration = (6 + Math.random() * 6) + 's';
            const size = 1 + Math.random() * 3;
            p.style.width = size + 'px';
            p.style.height = size + 'px';
            p.style.opacity = 0.2 + Math.random() * 0.4;
            container.appendChild(p);
        }
    }

    function initScrollReveal() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                }
            });
        }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

        document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
    }

    function setupUploadZone(zone, input, type) {
        if (!zone || !input) return;

        zone.addEventListener('click', () => input.click());

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('dragover');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) handleFile(file, zone, type);
        });

        input.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) handleFile(file, zone, type);
        });
    }

    function handleFile(file, zone, type) {
        if (type === 'video') {
            videoFile = file;
        } else {
            audioFile = file;
        }

        zone.classList.add('has-file');
        const iconEl = zone.querySelector('.upload-icon');
        const textEl = zone.querySelector('.upload-text');
        const formatsEl = zone.querySelector('.upload-formats');

        if (iconEl) iconEl.textContent = '✅';
        if (textEl) textEl.innerHTML = `
            <div class="upload-filename">${file.name}</div>
            <div class="upload-filesize">${(file.size / 1024 / 1024).toFixed(1)} MB</div>
        `;
        if (formatsEl) formatsEl.textContent = 'Click to change file';

        updateRenderButton();
    }

    function updateRenderButton() {
        renderBtn.disabled = !(videoFile && audioFile);
    }

    async function startRender() {
        if (!videoFile || !audioFile) {
            showToast('Please upload both a video and audio file');
            return;
        }

        // Show progress
        progressSection.classList.add('active');
        outputSection.classList.remove('active');
        renderBtn.disabled = true;
        renderBtn.textContent = 'RENDERING...';

        // Scroll to progress
        progressSection.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Build form data
        const formData = new FormData();
        formData.append('video', videoFile);
        formData.append('audio', audioFile);
        formData.append('preset', selectedPreset);
        formData.append('intensity', intensitySlider.value);
        formData.append('quality', selectedQuality);

        try {
            const res = await fetch('/render', { method: 'POST', body: formData });
            const data = await res.json();

            if (data.error) {
                showToast(data.error);
                resetRenderBtn();
                return;
            }

            // Poll for status
            pollStatus(data.job_id);

        } catch (err) {
            showToast('Connection error: ' + err.message);
            resetRenderBtn();
        }
    }

    function pollStatus(jobId) {
        let failCount = 0;
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`/status/${jobId}`);
                const data = await res.json();

                if (!res.ok || data.error === 'Job not found') {
                    failCount++;
                    if (failCount > 5) {
                        clearInterval(interval);
                        showToast('Job lost — server may have restarted. Please try again.');
                        resetRenderBtn();
                        progressSection.classList.remove('active');
                    }
                    return;
                }

                failCount = 0;
                updateProgress(data);

                if (data.status === 'done') {
                    clearInterval(interval);
                    showOutput(jobId, data);
                    resetRenderBtn();
                } else if (data.status === 'error') {
                    clearInterval(interval);
                    showToast('Render error: ' + (data.error || 'Unknown'));
                    resetRenderBtn();
                    progressSection.classList.remove('active');
                }
            } catch (err) {
                failCount++;
                if (failCount > 10) {
                    clearInterval(interval);
                    showToast('Connection lost. Please try again.');
                    resetRenderBtn();
                    progressSection.classList.remove('active');
                }
            }
        }, 1000);
    }

    function updateProgress(data) {
        const fill = document.getElementById('progressFill');
        const pct = document.getElementById('progressPct');
        const step = document.getElementById('progressStep');
        const bpmVal = document.getElementById('bpmValue');
        const beatsVal = document.getElementById('beatsValue');
        const statusVal = document.getElementById('statusValue');

        const prog = data.progress || 0;
        if (fill) fill.style.width = prog + '%';
        if (pct) pct.textContent = prog + '%';
        if (step) step.textContent = data.step || 'Processing...';
        if (bpmVal && data.tempo) bpmVal.textContent = Math.round(data.tempo);
        if (beatsVal && data.beats) beatsVal.textContent = data.beats;
        if (statusVal) statusVal.textContent = data.status ? data.status.toUpperCase() : 'ACTIVE';
    }

    function showOutput(jobId, data) {
        progressSection.classList.remove('active');
        outputSection.classList.add('active');

        const video = document.getElementById('outputVideo');
        const dlBtn = document.getElementById('downloadBtn');

        if (video) video.src = `/download/${jobId}`;
        if (dlBtn) dlBtn.href = `/download/${jobId}`;

        outputSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function resetRenderBtn() {
        renderBtn.disabled = !(videoFile && audioFile);
        renderBtn.innerHTML = '⚡ &nbsp; EXECUTE CINEMATIC RENDER &nbsp; ⚡';
    }

    function showToast(message) {
        let toast = document.getElementById('toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'toast';
            toast.classList.add('toast');
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 4000);
    }

});
