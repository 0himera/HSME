const API_BASE = "/api";

document.addEventListener("DOMContentLoaded", () => {
    loadExperiments();

    // Event listeners
    document.getElementById("search-form").addEventListener("submit", handleSearch);
    document.getElementById("ingest-form").addEventListener("submit", handleIngest);
    document.getElementById("gap-form").addEventListener("submit", handleGapAnalysis);
});

// Helper: Parse Type:Value strings into Entity objects
function parseEntities(str) {
    if (!str || !str.trim()) return [];
    return str.split(",").map(part => {
        const separatorIndex = part.indexOf(":");
        if (separatorIndex === -1) {
            return { type: "Tag", value: part.trim() };
        }
        return {
            type: part.substring(0, separatorIndex).trim(),
            value: part.substring(separatorIndex + 1).trim()
        };
    });
}

// Helper: Helper to convert list of strings (split by comma)
function parseCsv(str) {
    if (!str || !str.trim()) return [];
    return str.split(",").map(s => s.trim());
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
            nameTd.innerHTML = `<strong>${exp.id}</strong><br><small>${exp.name}</small>`;
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
                procTd.innerHTML += `<span class="badge">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(procTd);
            
            // Outputs
            const outputsTd = document.createElement("td");
            exp.output_entities.forEach(ent => {
                outputsTd.innerHTML += `<span class="badge" style="background:#d4edda; border-color:#c3e6cb;">${ent.type}: ${ent.value}</span> `;
            });
            tr.appendChild(outputsTd);
            
            // Confidence / Evidence
            const evTd = document.createElement("td");
            evTd.innerHTML = `Confidence: <strong>${exp.confidence}</strong><br>`;
            exp.evidence.forEach(file => {
                evTd.innerHTML += `<small class="badge" style="background:#e8f4fd;">${file}</small> `;
            });
            tr.appendChild(evTd);
            
            // Actions
            const actionsTd = document.createElement("td");
            actionsTd.innerHTML = `
                <button class="action-btn" onclick="showCausalReasoning('${exp.id}')">CAUSAL REASON</button>
                <button class="action-btn" onclick="showCounterfactuals('${exp.id}')">CF RETRIEVAL</button>
            `;
            tr.appendChild(actionsTd);
            
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error(err);
        alert("Error loading database experiments.");
    }
}

// Handle search form
async function handleSearch(e) {
    e.preventDefault();
    const queryText = document.getElementById("search-input").value;
    const queryEntities = parseEntities(queryText);
    
    if (queryEntities.length === 0) {
        alert("Please enter at least one query entity.");
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/search`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ entities: queryEntities, limit: 5 })
        });
        
        if (!response.ok) throw new Error("Search request failed");
        const results = await response.json();
        
        const resultsSection = document.getElementById("search-results-section");
        const resultsDiv = document.getElementById("search-results");
        resultsSection.style.display = "block";
        resultsDiv.innerHTML = "";
        
        if (results.length === 0) {
            resultsDiv.innerHTML = "<p>No matches found.</p>";
            return;
        }
        
        const table = document.createElement("table");
        table.innerHTML = `
            <thead>
                <tr>
                    <th>Experiment ID & Name</th>
                    <th>Similarity Score</th>
                    <th>Matched Entities</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        
        const tbody = table.querySelector("tbody");
        results.forEach(res => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${res.experiment.id}</strong><br><small>${res.experiment.name}</small></td>
                <td><strong>${(res.similarity * 100).toFixed(1)}%</strong></td>
                <td>
                    ${res.experiment.input_entities.map(e => `<span class="badge">${e.type}:${e.value}</span>`).join(" ")}
                </td>
            `;
            tbody.appendChild(tr);
        });
        
        resultsDiv.appendChild(table);
    } catch (err) {
        console.error(err);
        alert("Error performing search.");
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
        confidence: parseFloat(document.getElementById("exp-confidence").value)
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
        
        alert("Experiment ingested and VSA hypervector created successfully!");
        document.getElementById("ingest-form").reset();
        document.getElementById("exp-confidence").value = "0.95"; // Reset default
        loadExperiments();
    } catch (err) {
        console.error(err);
        alert(`Error ingesting experiment: ${err.message}`);
    }
}

// Perform Causal Reasoning
async function showCausalReasoning(expId) {
    const logger = document.getElementById("reasoner-output");
    logger.textContent = `Running causal inference calculations for ${expId}...`;
    
    try {
        const response = await fetch(`${API_BASE}/reason/${expId}`);
        if (!response.ok) throw new Error("Causal reasoning failed");
        const data = await response.json();
        logger.textContent = data.explanation;
    } catch (err) {
        logger.textContent = `Error performing causal reasoning: ${err.message}`;
    }
}

// Fetch and display raw counterfactual neighbors
async function showCounterfactuals(expId) {
    const logger = document.getElementById("reasoner-output");
    logger.textContent = `Finding topological counterfactual neighbors (distance = 1 parameter change) for ${expId}...`;
    
    try {
        const response = await fetch(`${API_BASE}/counterfactuals/${expId}`);
        if (!response.ok) throw new Error("CF retrieval failed");
        const cfs = await response.json();
        
        if (cfs.length === 0) {
            logger.textContent = `No matching counterfactual experiments found for ${expId} in the database.`;
            return;
        }
        
        let report = `### Counterfactual Neighbors for ${expId}\n\n`;
        cfs.forEach((cf, idx) => {
            report += `[${idx+1}] Match: ${cf.experiment.id} ("${cf.experiment.name}")\n`;
            report += `    Parameter Changed: ${cf.difference.parameter} (${cf.difference.from} -> ${cf.difference.to})\n`;
            report += `    Outputs Difference:\n`;
            cf.effects.forEach(eff => {
                report += `      * ${eff.property}: ${eff.from} -> ${eff.to}\n`;
            });
            report += "\n";
        });
        
        logger.textContent = report;
    } catch (err) {
        logger.textContent = `Error retrieving counterfactuals: ${err.message}`;
    }
}

// Run Gap Analysis
async function handleGapAnalysis(e) {
    e.preventDefault();
    const dimsText = document.getElementById("gap-dimensions").value;
    const dimensions = parseCsv(dimsText);
    
    if (dimensions.length === 0) {
        alert("Please specify at least one dimension.");
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
            tbody.innerHTML = "<tr><td colspan='3'>No gaps found across the selected dimensions. All coordinates are explored.</td></tr>";
            return;
        }
        
        gaps.forEach((gap, idx) => {
            const tr = document.createElement("tr");
            
            // Combination representation
            const comboText = gap.configuration.map(e => `${e.type}: ${e.value}`).join("<br>");
            const comboTd = document.createElement("td");
            comboTd.innerHTML = `<strong>${comboText}</strong>`;
            tr.appendChild(comboTd);
            
            // Neighbors
            const neighTd = document.createElement("td");
            neighTd.textContent = gap.similar_experiments.join(", ") || "None";
            tr.appendChild(neighTd);
            
            // Action
            const actionTd = document.createElement("td");
            const btn = document.createElement("button");
            btn.textContent = "ENRICH & HYPOTHESIZE";
            btn.className = "action-btn";
            
            // Store gap data in button data-attribute to retrieve on click
            btn.addEventListener("click", () => enrichGap(gap.configuration));
            actionTd.appendChild(btn);
            tr.appendChild(actionTd);
            
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error(err);
        alert("Error performing gap analysis.");
    }
}

// Enrich Gap (Extrapolate missing manifold values)
async function enrichGap(gapConfig) {
    const logger = document.getElementById("reasoner-output");
    logger.textContent = "Computing manifold boundary projections and extrapolating properties...";
    
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
        logger.textContent = `Error enriching gap: ${err.message}`;
    }
}
