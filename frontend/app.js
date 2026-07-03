const API_BASE = "/api";
let networkGraph = null;

document.addEventListener("DOMContentLoaded", () => {
    // Initial loads
    loadExperiments();
    updateStatistics();
    drawGraph();
    checkIngestionStatus();

    // Event listeners
    document.getElementById("search-form").addEventListener("submit", handleSearch);
    document.getElementById("ingest-form").addEventListener("submit", handleIngest);
    document.getElementById("gap-form").addEventListener("submit", handleGapAnalysis);
    document.getElementById("btn-ingest-corpus").addEventListener("click", triggerCorpusIngestion);

    // Poll status occasionally if ingestion is running
    setInterval(checkIngestionStatus, 5000);
});

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
        const response = await fetch(`${API_BASE}/statistics`);
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
        const response = await fetch(`${API_BASE}/ingest-status`);
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
            // Refresh data since new files have been ingested
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
        const response = await fetch(`${API_BASE}/ingest-corpus`, { method: "POST" });
        if (!response.ok) throw new Error("Trigger request failed");
        checkIngestionStatus();
    } catch (err) {
        alert("Failed to start background ingestion: " + err.message);
        checkIngestionStatus();
    }
}

// Load and render all experiments
async function loadExperiments() {
    try {
        const response = await fetch(`${API_BASE}/experiments`);
        if (!response.ok) throw new Error("Failed to load experiments");
        const experiments = await response.json();
        
        const tbody = document.querySelector("#experiments-table tbody");
        tbody.innerHTML = "";
        
        experiments.forEach(exp => {
            const tr = document.createElement("tr");
            
            // Name
            const nameTd = document.createElement("td");
            const geoBadge = `<span class="badge badge-source" style="font-size:0.75rem;">${exp.geography || "Global"}</span>`;
            const yearBadge = exp.year ? `<span class="badge" style="font-size:0.75rem; background:rgba(255,255,255,0.05); color:var(--text-muted); border-color:var(--border-color);">${exp.year}</span>` : "";
            nameTd.innerHTML = `<strong>${exp.id}</strong><br><small>${exp.name}</small><br>${geoBadge} ${yearBadge}`;
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
                procTd.innerHTML += `<span class="badge" style="background:rgba(52,152,219,0.15); border-color:rgba(52,152,219,0.3); color:#9bd2f8;">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(procTd);
            
            // Outputs
            const outputsTd = document.createElement("td");
            exp.output_entities.forEach(ent => {
                outputsTd.innerHTML += `<span class="badge badge-output">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(outputsTd);
            
            // Actions
            const actionsTd = document.createElement("td");
            actionsTd.innerHTML = `
                <div style="display:flex; flex-direction:column; gap:5px;">
                    <button class="action-btn-sm" onclick="showCausalReasoning('${exp.id}')">ВЫВОД СВЯЗЕЙ</button>
                    <button class="action-btn-sm btn-secondary" onclick="showCounterfactuals('${exp.id}')">КОНТРФАКТЫ</button>
                </div>
            `;
            tr.appendChild(actionsTd);
            
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error(err);
    }
}

// Handle search form
async function handleSearch(e) {
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
    
    const payload = {
        entities: queryEntities,
        limit: 5,
        year_start: yearStartVal ? parseInt(yearStartVal) : null,
        year_end: yearEndVal ? parseInt(yearEndVal) : null,
        geography: geographyVal || null,
        source_type: sourceVal || null
    };
    
    try {
        const response = await fetch(`${API_BASE}/search`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error("Search request failed");
        const results = await response.json();
        
        const resultsSection = document.getElementById("search-results-section");
        const resultsDiv = document.getElementById("search-results");
        resultsSection.style.display = "block";
        resultsDiv.innerHTML = "";
        
        if (results.length === 0) {
            resultsDiv.innerHTML = "<p style='color:var(--text-muted); padding:10px;'>Экспериментов с такими условиями или фильтрами не найдено.</p>";
            return;
        }
        
        const table = document.createElement("table");
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Эксперимент (ID & Метаданные)</th>
                    <th>Степень сходства (VSA)</th>
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
        
        // Highlight corresponding nodes in the visual graph
        if (networkGraph && results.length > 0) {
            const bestNodeId = `exp_${results[0].experiment.id}`;
            networkGraph.selectNodes([bestNodeId]);
            networkGraph.focus(bestNodeId, { scale: 1.2, animation: true });
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
        source_type: "Статья"
    };
    
    try {
        const response = await fetch(`${API_BASE}/ingest`, {
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
    } catch (err) {
        console.error(err);
        alert(`Ошибка при добавлении: ${err.message}`);
    }
}

// Draw the visualizable network graph
async function drawGraph() {
    const container = document.getElementById("graph-container");
    
    try {
        const response = await fetch(`${API_BASE}/graph`);
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
                color: { color: "rgba(0, 0, 0, 0.15)", highlight: "#000000" },
                width: 1
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
                    showCausalReasoning(expId);
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
    logger.textContent = `[Reasoner] Запуск асинхронного логического вывода для ${expId}...\nАнализируем топологию контрфактов...`;
    
    try {
        const response = await fetch(`${API_BASE}/reason/${expId}`);
        if (!response.ok) throw new Error("Запрос аналитики отклонен сервером");
        const data = await response.json();
        logger.textContent = data.explanation;
    } catch (err) {
        logger.textContent = `Ошибка выполнения отчета: ${err.message}`;
    }
}

// Fetch and display raw counterfactual neighbors
async function showCounterfactuals(expId) {
    const logger = document.getElementById("reasoner-output");
    logger.textContent = `[Reasoner] Ищем контрфакты на расстоянии 1 изменения для ${expId}...`;
    
    try {
        const response = await fetch(`${API_BASE}/counterfactuals/${expId}`);
        if (!response.ok) throw new Error("Ошибка получения контрфактов");
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
        const response = await fetch(`${API_BASE}/gaps`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dimensions })
        });
        
        if (!response.ok) throw new Error("Gap analysis failed");
        const gaps = await response.json();
        
        const resultsSection = document.getElementById("gaps-results-section");
        const tbody = document.querySelector("#gaps-table tbody");
        resultsSection.style.display = "block";
        tbody.innerHTML = "";
        
        if (gaps.length === 0) {
            tbody.innerHTML = "<tr><td colspan='3' style='color:var(--text-muted); text-align:center;'>Все комбинации указанных факторов исследованы. Пробелов не обнаружено.</td></tr>";
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
            
            // Action
            const actionTd = document.createElement("td");
            const btn = document.createElement("button");
            btn.textContent = "СИНТЕЗ ГИПОТЕЗЫ";
            btn.className = "action-btn-sm";
            btn.style.width = "auto";
            
            btn.addEventListener("click", () => enrichGap(gap.configuration));
            actionTd.appendChild(btn);
            tr.appendChild(actionTd);
            
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error(err);
        alert("Ошибка проведения анализа пробелов.");
    }
}

// Enrich Gap (Extrapolate properties and call YandexGPT 5.1)
async function enrichGap(gapConfig) {
    const logger = document.getElementById("reasoner-output");
    logger.textContent = "[Reasoner] Расчет проекций пробела на границу многообразия...\nЗапуск YandexGPT 5.1 для формулирования гипотезы...";
    
    try {
        const response = await fetch(`${API_BASE}/enrich-gap`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(gapConfig)
        });
        
        if (!response.ok) throw new Error("Auto-enrichment request failed");
        const data = await response.json();
        logger.textContent = data.hypothesis;
    } catch (err) {
        logger.textContent = `Ошибка генерации гипотезы: ${err.message}`;
    }
}
