const API_BASE = "/api";
let networkGraph = null;

// Security and User State
let currentUser = "admin";
let currentRole = "Administrator";

// Pagination State
let currentExpPage = 0;
const expPageSize = 5;

let currentSearchPage = 0;
const searchPageSize = 3;
let lastSearchPayload = null;

document.addEventListener("DOMContentLoaded", () => {
    // Sync active role from storage
    const savedUserSelect = localStorage.getItem("hsme_user_select");
    if (savedUserSelect) {
        const parts = savedUserSelect.split(":");
        currentUser = parts[0];
        currentRole = parts[1];
        document.getElementById("current-user-select").value = savedUserSelect;
    } else {
        document.getElementById("current-user-select").value = "admin:Administrator";
    }

    // Initial loads
    loadExperiments();
    updateStatistics();
    drawGraph();
    checkIngestionStatus();
    renderRoleControls();

    // Event listeners
    document.getElementById("search-form").addEventListener("submit", handleSearchSubmit);
    document.getElementById("ingest-form").addEventListener("submit", handleIngest);
    document.getElementById("gap-form").addEventListener("submit", handleGapAnalysis);
    document.getElementById("btn-ingest-corpus").addEventListener("click", triggerCorpusIngestion);
    
    // User role selector listener
    document.getElementById("current-user-select").addEventListener("change", (e) => {
        const val = e.target.value;
        localStorage.setItem("hsme_user_select", val);
        const parts = val.split(":");
        currentUser = parts[0];
        currentRole = parts[1];
        
        // Reset page indexes
        currentExpPage = 0;
        currentSearchPage = 0;
        lastSearchPayload = null;
        document.getElementById("search-results-section").style.display = "none";
        document.getElementById("search-pagination").style.display = "none";
        
        // Reload all data
        loadExperiments();
        updateStatistics();
        drawGraph();
        checkIngestionStatus();
        renderRoleControls();
    });

    // Pagination listeners
    document.getElementById("btn-exp-prev").addEventListener("click", () => {
        if (currentExpPage > 0) {
            currentExpPage--;
            loadExperiments();
        }
    });
    document.getElementById("btn-exp-next").addEventListener("click", () => {
        currentExpPage++;
        loadExperiments();
    });

    document.getElementById("btn-search-prev").addEventListener("click", () => {
        if (currentSearchPage > 0) {
            currentSearchPage--;
            loadSearchPage();
        }
    });
    document.getElementById("btn-search-next").addEventListener("click", () => {
        currentSearchPage++;
        loadSearchPage();
    });

    // Poll status occasionally if ingestion is running
    setInterval(checkIngestionStatus, 5000);
});

// Helper: Fetch wrapper that automatically injects user identity headers
async function fetchWithAuth(url, options = {}) {
    options.headers = options.headers || {};
    options.headers["X-User-Name"] = currentUser;
    options.headers["X-User-Role"] = currentRole;
    return fetch(url, options);
}

// Adjust UI component visibility based on the selected user role
function renderRoleControls() {
    const isPartner = currentRole === "External Partner";
    const isResearcher = currentRole === "Researcher";
    const isAnalyst = currentRole === "Analyst";
    const isAdmin = currentRole === "Administrator";
    
    // Ingest corpus and ingest manual forms (Admin only)
    const ingestCorpusCard = document.getElementById("btn-ingest-corpus").closest(".card");
    if (ingestCorpusCard) ingestCorpusCard.style.display = isAdmin ? "block" : "none";
    
    const ingestFormCard = document.getElementById("ingest-form").closest(".card");
    if (ingestFormCard) ingestFormCard.style.display = isAdmin ? "block" : "none";
    
    // Gaps card (Admin, Analyst, Researcher)
    const gapCard = document.getElementById("gap-form").closest(".card");
    if (gapCard) gapCard.style.display = isPartner ? "none" : "block";
    
    // Audit logs card (Admin only)
    const auditLogCard = document.getElementById("audit-log-card");
    if (auditLogCard) {
        if (isAdmin) {
            auditLogCard.style.display = "block";
            loadAuditLogs();
        } else {
            auditLogCard.style.display = "none";
        }
    }
}

// Helper: Parse Type:Value strings into Entity objects
function parseEntities(str) {
    if (!str || !str.trim()) return [];
    return str.split(",").map(part => {
        const separatorIndex = part.indexOf(":");
        if (separatorIndex === -1) {
            return { type: "Property", value: part.trim() };
        }
        return {
            type: part.substring(0, separatorIndex).trim(),
            value: part.substring(separatorIndex + 1).trim()
        };
    });
}

// Helper: Convert list of strings (split by comma)
function parseCsv(str) {
    if (!str || !str.trim()) return [];
    return str.split(",").map(s => s.trim());
}

// Update upper dashboard stat badges
async function updateStatistics() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/statistics`);
        if (!response.ok) throw new Error("Failed to load statistics");
        const stats = await response.json();
        
        document.getElementById("stat-experiments").textContent = stats.total_experiments;
        document.getElementById("stat-materials").textContent = stats.distinct_counts["Material"] || 0;
        document.getElementById("stat-processes").textContent = stats.distinct_counts["Process"] || 0;
    } catch (err) {
        console.error("Stats update failed:", err);
    }
}

// Check background ingestion status
async function checkIngestionStatus() {
    const statusText = document.getElementById("ingest-status-text");
    const btn = document.getElementById("btn-ingest-corpus");
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/ingest-status`);
        if (!response.ok) return;
        const status = await response.json();
        
        if (status.status === "running") {
            statusText.innerHTML = `<span class="status-dot running"></span> Импорт выполняется... (Обработано: ${status.files_indexed} файлов, чанков: ${status.total_chunks})`;
            btn.disabled = true;
            btn.textContent = "Импорт идет...";
        } else if (status.status === "completed") {
            statusText.innerHTML = `<span class="status-dot completed"></span> Импорт завершен! Загружено ${status.files_indexed} файлов (${status.total_chunks} фактов)`;
            btn.disabled = false;
            btn.textContent = "Импортировать корпус";
            // Refresh data
            loadExperiments();
            updateStatistics();
            drawGraph();
        } else if (status.status === "failed") {
            statusText.innerHTML = `<span class="status-dot" style="background:#e74c3c;"></span> Ошибка импорта: ${status.error}`;
            btn.disabled = false;
            btn.textContent = "Повторить импорт";
        } else {
            statusText.innerHTML = `<span class="status-dot"></span> Статус: готов к запуску`;
            btn.disabled = false;
        }
    } catch (err) {
        console.error("Failed to check ingestion status:", err);
    }
}

// Trigger background corpus ingestion
async function triggerCorpusIngestion() {
    const statusText = document.getElementById("ingest-status-text");
    const btn = document.getElementById("btn-ingest-corpus");
    
    statusText.innerHTML = `<span class="status-dot running"></span> Запуск импорта...`;
    btn.disabled = true;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/ingest-corpus`, { method: "POST" });
        if (!response.ok) throw new Error("Trigger request failed");
        checkIngestionStatus();
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        alert("Failed to start background ingestion: " + err.message);
        checkIngestionStatus();
    }
}

// Load and render paged experiments
async function loadExperiments() {
    try {
        const skip = currentExpPage * expPageSize;
        const response = await fetchWithAuth(`${API_BASE}/experiments?skip=${skip}&limit=${expPageSize}&paged=true`);
        if (!response.ok) throw new Error("Failed to load experiments");
        
        const data = await response.json();
        const experiments = data.experiments;
        const total = data.total;
        
        const tbody = document.querySelector("#experiments-table tbody");
        tbody.innerHTML = "";
        
        if (experiments.length === 0) {
            tbody.innerHTML = "<tr><td colspan='5' style='color:var(--text-muted); text-align:center;'>Список пуст (или недостаточно прав).</td></tr>";
            return;
        }
        
        experiments.forEach(exp => {
            const tr = document.createElement("tr");
            
            // Name
            const nameTd = document.createElement("td");
            const geoBadge = `<span class="badge badge-source" style="font-size:0.75rem;">${exp.geography || "Global"}</span>`;
            const yearBadge = exp.year ? `<span class="badge" style="font-size:0.75rem; background:rgba(0,0,0,0.05); color:#555; border-color:#ccc;">${exp.year}</span>` : "";
            const sensitiveBadge = exp.is_sensitive ? `<span class="badge" style="font-size:0.75rem; background:#fee; border-color:#fcc; color:#c00;">Приватный</span>` : "";
            nameTd.innerHTML = `<strong>${exp.id}</strong><br><small>${exp.name}</small><br>${geoBadge} ${yearBadge} ${sensitiveBadge}`;
            tr.appendChild(nameTd);
            
            // Inputs
            const inputsTd = document.createElement("td");
            exp.input_entities.forEach(ent => {
                inputsTd.innerHTML += `<span class="badge">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(inputsTd);
            
            // Processes
            const procTd = document.createElement("td");
            exp.process_entities.forEach(ent => {
                procTd.innerHTML += `<span class="badge" style="background:rgba(52,152,219,0.1); border-color:rgba(52,152,219,0.3); color:#2980b9;">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(procTd);
            
            // Outputs
            const outputsTd = document.createElement("td");
            exp.output_entities.forEach(ent => {
                outputsTd.innerHTML += `<span class="badge badge-output">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(outputsTd);
            
            // Actions (Disabled or hidden depending on roles)
            const actionsTd = document.createElement("td");
            const isPartner = currentRole === "External Partner";
            const isResearcher = currentRole === "Researcher";
            const isAnalyst = currentRole === "Analyst";
            const isAdmin = currentRole === "Administrator";
            
            if (isPartner) {
                actionsTd.innerHTML = `<span style="color:#777; font-size:0.75rem; font-weight:bold;">НЕТ ДОСТУПА</span>`;
            } else {
                const reasonBtn = (isAdmin || isAnalyst) 
                    ? `<button class="action-btn-sm" onclick="showCausalReasoning('${exp.id}')">ВЫВОД СВЯЗЕЙ</button>`
                    : `<button class="action-btn-sm" disabled title="Анализ доступен только Аналитикам">ВЫВОД СВЯЗЕЙ</button>`;
                const cfBtn = `<button class="action-btn-sm btn-secondary" onclick="showCounterfactuals('${exp.id}')">КОНТРФАКТЫ</button>`;
                
                actionsTd.innerHTML = `
                    <div style="display:flex; flex-direction:column; gap:5px;">
                        ${reasonBtn}
                        ${cfBtn}
                    </div>
                `;
            }
            tr.appendChild(actionsTd);
            tbody.appendChild(tr);
        });
        
        // Render pagination info
        const totalPages = Math.max(1, Math.ceil(total / expPageSize));
        document.getElementById("exp-page-info").textContent = `СТРАНИЦА ${currentExpPage + 1} ИЗ ${totalPages}`;
        document.getElementById("btn-exp-prev").disabled = (currentExpPage === 0);
        document.getElementById("btn-exp-next").disabled = (currentExpPage >= totalPages - 1);
    } catch (err) {
        console.error(err);
    }
}

// Handle submit on the search form (resets to page 0)
async function handleSearchSubmit(e) {
    e.preventDefault();
    const queryText = document.getElementById("search-input").value;
    const queryEntities = parseEntities(queryText);
    
    if (queryEntities.length === 0) {
        alert("Пожалуйста, введите хотя бы одну сущность для поиска.");
        return;
    }
    
    const yearStartVal = document.getElementById("filter-year-start").value;
    const yearEndVal = document.getElementById("filter-year-end").value;
    const geographyVal = document.getElementById("filter-geography").value;
    const sourceVal = document.getElementById("filter-source").value;
    
    lastSearchPayload = {
        entities: queryEntities,
        year_start: yearStartVal ? parseInt(yearStartVal) : null,
        year_end: yearEndVal ? parseInt(yearEndVal) : null,
        geography: geographyVal || null,
        source_type: sourceVal || null
    };
    
    currentSearchPage = 0;
    loadSearchPage();
}

// Execute the paginated search and render results
async function loadSearchPage() {
    if (!lastSearchPayload) return;
    
    const skip = currentSearchPage * searchPageSize;
    const payload = {
        ...lastSearchPayload,
        skip: skip,
        limit: searchPageSize,
        paged: true
    };
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/search`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error("Search request failed");
        const data = await response.json();
        const results = data.results;
        const total = data.total;
        
        const resultsSection = document.getElementById("search-results-section");
        const resultsDiv = document.getElementById("search-results");
        resultsSection.style.display = "block";
        resultsDiv.innerHTML = "";
        
        if (results.length === 0) {
            resultsDiv.innerHTML = "<p style='color:#777; padding:10px;'>Экспериментов с такими условиями не найдено (или ограничено ролевой моделью).</p>";
            document.getElementById("search-pagination").style.display = "none";
            return;
        }
        
        const table = document.createElement("table");
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Эксперимент (ID & Метаданные)</th>
                    <th>Сходство (VSA)</th>
                    <th>Входные условия (Inputs)</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        
        const tbody = table.querySelector("tbody");
        results.forEach(res => {
            const tr = document.createElement("tr");
            const scorePercent = (res.similarity * 100).toFixed(1);
            const scoreColor = res.similarity > 0.1 ? "#20c997" : (res.similarity > 0.03 ? "#f1c40f" : "#e74c3c");
            
            tr.innerHTML = `
                <td><strong>${res.experiment.id}</strong><br><small>${res.experiment.name}</small></td>
                <td style="color:${scoreColor}; font-weight:700;">${scorePercent}%</td>
                <td>
                    ${res.experiment.input_entities.map(e => `<span class="badge">${e.type}:${e.value}</span>`).join(" ")}
                </td>
            `;
            tbody.appendChild(tr);
        });
        
        resultsDiv.appendChild(table);
        
        // Show pagination panel
        document.getElementById("search-pagination").style.display = "flex";
        const totalPages = Math.max(1, Math.ceil(total / searchPageSize));
        document.getElementById("search-page-info").textContent = `СТРАНИЦА ${currentSearchPage + 1} ИЗ ${totalPages}`;
        document.getElementById("btn-search-prev").disabled = (currentSearchPage === 0);
        document.getElementById("btn-search-next").disabled = (currentSearchPage >= totalPages - 1);
        
        // Highlight best node in the visual graph
        if (networkGraph && results.length > 0) {
            const bestNodeId = `exp_${results[0].experiment.id}`;
            networkGraph.selectNodes([bestNodeId]);
            networkGraph.focus(bestNodeId, { scale: 1.2, animation: true });
        }
        
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        console.error(err);
        alert("Ошибка выполнения поиска.");
    }
}

// Handle Ingestion Form
async function handleIngest(e) {
    e.preventDefault();
    const payload = {
        id: document.getElementById("exp-id").value.trim(),
        name: document.getElementById("exp-name").value.trim(),
        input_entities: parseEntities(document.getElementById("exp-inputs").value),
        process_entities: parseEntities(document.getElementById("exp-processes").value),
        output_entities: parseEntities(document.getElementById("exp-outputs").value),
        evidence: parseCsv(document.getElementById("exp-evidence").value),
        confidence: 0.95,
        year: 2026,
        geography: "RU",
        source_type: "Статья",
        is_sensitive: false // Default to public manually added
    };
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/ingest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Ingestion failed");
        }
        
        alert("Эксперимент добавлен, VSA-вектор успешно сгенерирован и сохранен!");
        document.getElementById("ingest-form").reset();
        loadExperiments();
        updateStatistics();
        drawGraph();
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        console.error(err);
        alert(`Ошибка при добавлении: ${err.message}`);
    }
}

// Draw the visualizable network graph
async function drawGraph() {
    const container = document.getElementById("graph-container");
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/graph`);
        if (!response.ok) throw new Error("Failed to load graph data");
        const graphData = await response.json();
        
        // Custom styling based on groups
        const nodes = graphData.nodes.map(n => {
            let color = "#8a2be2"; // Purple for Experiments
            let shape = "dot";
            let size = 22;
            
            if (n.group === "Material") {
                color = "#20c997"; // Teal
                size = 15;
            } else if (n.group === "Process") {
                color = "#3498db"; // Blue
                size = 18;
            } else if (n.group === "Equipment") {
                color = "#f1c40f"; // Yellow
                size = 16;
            } else if (n.group === "Property") {
                color = "#00f2fe"; // Cyan
                size = 12;
                shape = "triangle";
            } else if (n.group === "Facility") {
                color = "#e74c3c"; // Red
                size = 16;
            } else if (n.group === "Publication") {
                color = "#95a5a6"; // Grey
                size = 14;
                shape = "square";
            } else if (n.group === "Expert") {
                color = "#fda7df"; // Pink
                size = 15;
            }
            
            return {
                id: n.id,
                label: n.label,
                title: n.title,
                color: {
                    background: color,
                    border: "#000000",
                    highlight: { background: "#ffffff", border: "#000000" }
                },
                shape: shape,
                size: size,
                font: { color: "#000000", face: "monospace", size: 12 }
            };
        });
        
        const data = {
            nodes: new vis.DataSet(nodes),
            edges: new vis.DataSet(graphData.edges.map(e => ({
                from: e.from,
                to: e.to,
                label: e.label || "",
                arrows: e.arrows || "",
                color: e.color || { color: "rgba(0, 0, 0, 0.15)", highlight: "#000000" },
                width: e.label && e.label !== "связан" ? 2 : 1,
                font: { color: "#ff5722", face: "monospace", size: 10, align: "top" }
            })))
        };
        
        const options = {
            physics: {
                barnesHut: {
                    gravitationalConstant: -1800,
                    centralGravity: 0.35,
                    springLength: 95,
                    springConstant: 0.04
                },
                stabilization: { iterations: 150 }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200
            }
        };
        
        networkGraph = new vis.Network(container, data, options);
        
        // Handle node clicks to load causal reasoning or details
        networkGraph.on("click", (params) => {
            if (params.nodes.length > 0) {
                const clickedId = params.nodes[0];
                if (clickedId.startsWith("exp_")) {
                    const expId = clickedId.replace("exp_", "");
                    const isPartner = currentRole === "External Partner";
                    if (isPartner) {
                        const logger = document.getElementById("reasoner-output");
                        logger.textContent = `[Permission Denied] Внешний партнер не имеет доступа к аналитике.`;
                    } else {
                        showCausalReasoning(expId);
                    }
                }
            }
        });
    } catch (err) {
        console.error("Draw graph failed:", err);
        container.innerHTML = `<div style="padding:40px; color:var(--text-muted); text-align:center;">Ошибка визуализации графа: ${err.message}</div>`;
    }
}

// Perform Causal Reasoning (Calls YandexGPT 5.1 API)
async function showCausalReasoning(expId) {
    const logger = document.getElementById("reasoner-output");
    
    if (currentRole !== "Administrator" && currentRole !== "Analyst") {
        logger.textContent = `[Permission Denied] Вывод связей доступен только для ролей Аналитик и Администратор. Ваша роль: ${currentRole}`;
        return;
    }
    
    logger.textContent = `[Reasoner] Запуск асинхронного логического вывода для ${expId}...\nАнализируем топологию контрфактов...`;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/reason/${expId}`);
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Запрос аналитики отклонен сервером");
        }
        const data = await response.json();
        logger.textContent = data.explanation;
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        logger.textContent = `Ошибка выполнения отчета: ${err.message}`;
    }
}

// Fetch and display raw counterfactual neighbors
async function showCounterfactuals(expId) {
    const logger = document.getElementById("reasoner-output");
    
    if (currentRole === "External Partner") {
        logger.textContent = `[Permission Denied] Контрфактический анализ недоступен для роли Внешний партнер.`;
        return;
    }
    
    logger.textContent = `[Reasoner] Ищем контрфакты на расстоянии 1 изменения для ${expId}...`;
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/counterfactuals/${expId}`);
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Ошибка получения контрфактов");
        }
        const cfs = await response.json();
        
        if (cfs.length === 0) {
            logger.textContent = `В базе данных не обнаружено экспериментов с разницей ровно в 1 параметр от ${expId}.`;
            return;
        }
        
        let report = `### КОНТРФАКТИЧЕСКИЙ АНАЛИЗ ДЛЯ ${expId}\n\n`;
        cfs.forEach((cf, idx) => {
            report += `[${idx+1}] Сходство с: ${cf.experiment.id} ("${cf.experiment.name}")\n`;
            report += `    Измененный фактор: ${cf.difference.parameter} (был: "${cf.difference.from}" стал: "${cf.difference.to}")\n`;
            report += `    Изменения в свойствах (эффекты):\n`;
            if (cf.effects.length === 0) {
                report += `      * Без значительных изменений в выходных свойствах.\n`;
            } else {
                cf.effects.forEach(eff => {
                    report += `      * ${eff.property}: с "${eff.from}" на "${eff.to}"\n`;
                });
            }
            report += "\n";
        });
        
        logger.textContent = report;
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        logger.textContent = `Ошибка вывода контрфактов: ${err.message}`;
    }
}

// Run Gap Analysis
async function handleGapAnalysis(e) {
    e.preventDefault();
    const dimsText = document.getElementById("gap-dimensions").value;
    const dimensions = parseCsv(dimsText);
    
    if (dimensions.length === 0) {
        alert("Укажите как минимум одно измерение.");
        return;
    }
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/gaps`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dimensions })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Gap analysis failed");
        }
        const gaps = await response.json();
        
        const resultsSection = document.getElementById("gaps-results-section");
        const tbody = document.querySelector("#gaps-table tbody");
        resultsSection.style.display = "block";
        tbody.innerHTML = "";
        
        if (gaps.length === 0) {
            tbody.innerHTML = "<tr><td colspan='3' style='color:#777; text-align:center;'>Все комбинации указанных факторов исследованы. Пробелов не обнаружено.</td></tr>";
            return;
        }
        
        gaps.forEach((gap, idx) => {
            const tr = document.createElement("tr");
            
            // Combination representation
            const comboText = gap.configuration.map(e => `<span class="badge">${e.type}: ${e.value}</span>`).join(" ");
            const comboTd = document.createElement("td");
            comboTd.innerHTML = `<strong>${comboText}</strong>`;
            tr.appendChild(comboTd);
            
            // Neighbors
            const neighTd = document.createElement("td");
            neighTd.textContent = gap.similar_experiments.join(", ") || "Нет близких";
            tr.appendChild(neighTd);
            
            // Action (Disabled for researchers)
            const actionTd = document.createElement("td");
            const btn = document.createElement("button");
            btn.textContent = "СИНТЕЗ ГИПОТЕЗЫ";
            btn.className = "action-btn-sm";
            btn.style.width = "auto";
            
            const isResearcher = currentRole === "Researcher";
            if (isResearcher) {
                btn.disabled = true;
                btn.title = "Доступно только Аналитикам и Администраторам";
            } else {
                btn.addEventListener("click", () => enrichGap(gap.configuration));
            }
            
            actionTd.appendChild(btn);
            tr.appendChild(actionTd);
            
            tbody.appendChild(tr);
        });
        
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        console.error(err);
        alert(`Ошибка проведения анализа пробелов: ${err.message}`);
    }
}

// Enrich Gap (Extrapolate properties and call YandexGPT 5.1)
async function enrichGap(gapConfig) {
    const logger = document.getElementById("reasoner-output");
    logger.textContent = "[Reasoner] Расчет проекций пробела на границу многообразия...\nЗапуск YandexGPT 5.1 для формулирования гипотезы...";
    
    try {
        const response = await fetchWithAuth(`${API_BASE}/enrich-gap`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(gapConfig)
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Auto-enrichment request failed");
        }
        const data = await response.json();
        logger.textContent = data.hypothesis;
        if (currentRole === "Administrator") {
            loadAuditLogs();
        }
    } catch (err) {
        logger.textContent = `Ошибка генерации гипотезы: ${err.message}`;
    }
}

// Load and render Audit logs (Administrator only)
async function loadAuditLogs() {
    try {
        const response = await fetchWithAuth(`${API_BASE}/audit-logs`);
        if (!response.ok) return;
        const logs = await response.json();
        const tbody = document.querySelector("#audit-table tbody");
        tbody.innerHTML = "";
        
        if (logs.length === 0) {
            tbody.innerHTML = "<tr><td colspan='4' style='color:#777; text-align:center;'>Журнал аудита пока пуст.</td></tr>";
            return;
        }
        
        // Show in reverse chronological order
        logs.slice().reverse().forEach(log => {
            const tr = document.createElement("tr");
            
            // Format time string
            const date = new Date(log.timestamp);
            const timeStr = date.toLocaleTimeString() + " " + date.toLocaleDateString();
            
            tr.innerHTML = `
                <td>${timeStr}</td>
                <td><strong>${log.username}</strong> (${log.role})</td>
                <td><span class="badge badge-source">${log.action}</span></td>
                <td><small>${log.details}</small></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Failed to load audit logs:", err);
    }
}
