// app.js — Lógica do painel VEGA

// Estado Global da Aplicação
const appState = {
    contracts: [],
    selectedContractId: null,
    alerts: [],
    statusFilter: "",
    maxUploadSizeMb: 25,
    pollingContracts: new Set(),
};

// URL Base da API (vazio se servido localmente a partir da raiz do FastAPI)
const API_BASE = "";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function finiteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
}

function optionalFiniteNumber(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

// Elementos da DOM
const dom = {
    systemModeBadge: document.getElementById("system-mode-badge"),
    systemStatusBadge: document.getElementById("system-status-badge"),
    dropzone: document.getElementById("contract-dropzone"),
    fileInput: document.getElementById("file-input"),
    vendorNameInput: document.getElementById("vendor-name-input"),
    uploadProgressContainer: document.getElementById("upload-progress-container"),
    uploadProgressFill: document.getElementById("upload-progress-fill"),
    uploadStatusText: document.getElementById("upload-status-text"),
    contractsList: document.getElementById("contracts-list"),
    contractsCount: document.getElementById("contracts-count"),
    statusFilter: document.getElementById("status-filter"),
    
    // Métricas
    avgHealthScore: document.getElementById("avg-health-score"),
    avgHealthBar: document.getElementById("avg-health-bar"),
    criticalContractsCount: document.getElementById("critical-contracts-count"),
    criticalContractsPct: document.getElementById("critical-contracts-pct"),
    totalFinancialValue: document.getElementById("total-financial-value"),
    
    // Timeline
    renewalTimeline: document.getElementById("renewal-timeline"),
    
    // Visualizador de Detalhes
    welcomePanel: document.getElementById("welcome-panel"),
    detailsViewer: document.getElementById("contract-details-viewer"),
    btnCloseViewer: document.getElementById("btn-close-viewer"),
    viewContractTitle: document.getElementById("view-contract-title"),
    viewContractVendor: document.getElementById("view-contract-vendor"),
    viewVendorRisk: document.getElementById("view-vendor-risk"),
    btnReanalyze: document.getElementById("btn-reanalyze"),
    btnTerminate: document.getElementById("btn-terminate"),
    btnOpenPdf: document.getElementById("btn-open-pdf"),
    
    // Detalhes do contrato
    viewContractStatus: document.getElementById("view-contract-status"),
    viewAnalysisStatus: document.getElementById("view-analysis-status"),
    analysisMessage: document.getElementById("analysis-message"),
    viewContractHealth: document.getElementById("view-contract-health"),
    viewContractStartDate: document.getElementById("view-contract-start-date"),
    viewContractEndDate: document.getElementById("view-contract-end-date"),
    viewContractAutorenew: document.getElementById("view-contract-autorenew"),
    viewContractNoticeDays: document.getElementById("view-contract-notice-days"),
    viewContractValue: document.getElementById("view-contract-value"),
    viewContractFrequency: document.getElementById("view-contract-frequency"),
    
    // Chat Q&A
    chatBox: document.getElementById("chat-box"),
    chatInput: document.getElementById("chat-input"),
    btnSendChat: document.getElementById("btn-send-chat"),
    
    // Listas internas
    clausesList: document.getElementById("clauses-list"),
    evidenceList: document.getElementById("evidence-list"),
    intelList: document.getElementById("intel-list"),
};

// --- INICIALIZAÇÃO ---
document.addEventListener("DOMContentLoaded", () => {
    initApp();
    setupEventListeners();
});

function initApp() {
    fetchSystemStatus();
    fetchContracts();
    fetchUpcomingAlerts();
    fetchValueLeakage();
}

// --- CONFIGURAÇÃO DE EVENTOS ---
function setupEventListeners() {
    // Dropzone Click & Change
    dom.dropzone.addEventListener("click", (e) => {
        // Evita clicar no file input repetidamente se clicado dentro do input-group
        if (e.target.id !== "vendor-name-input" && e.target.tagName !== "LABEL") {
            dom.fileInput.click();
        }
    });
    
    dom.fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileUpload(e.target.files[0]);
        }
    });

    // Dropzone Drag & Drop
    ["dragenter", "dragover"].forEach(eventName => {
        dom.dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dom.dropzone.classList.add("dragover");
        }, false);
    });

    ["dragleave", "drop"].forEach(eventName => {
        dom.dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dom.dropzone.classList.remove("dragover");
        }, false);
    });

    dom.dropzone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            handleFileUpload(files[0]);
        }
    });

    // Filtro de Status
    dom.statusFilter.addEventListener("change", (e) => {
        appState.statusFilter = e.target.value;
        renderContractsList();
    });

    // Fechar Visualizador
    dom.btnCloseViewer.addEventListener("click", () => {
        dom.detailsViewer.style.display = "none";
        dom.welcomePanel.style.display = "flex";
        appState.selectedContractId = null;
        
        // Remove a seleção visual
        const selectedItem = document.querySelector(".contract-item.selected");
        if (selectedItem) selectedItem.classList.remove("selected");
    });

    // Reanalisar Contrato
    dom.btnReanalyze.addEventListener("click", () => {
        if (appState.selectedContractId) {
            triggerReanalysis(appState.selectedContractId);
        }
    });

    // 1-Click Terminate
    dom.btnTerminate.addEventListener("click", () => {
        if (appState.selectedContractId) {
            triggerTermination(appState.selectedContractId);
        }
    });

    // Q&A Chat Submit
    dom.btnSendChat.addEventListener("click", submitQuestion);
    dom.chatInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            submitQuestion();
        }
    });
}

// --- CHAMADAS DA API ---

// 1. Status do Sistema
async function fetchSystemStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/system/status`);
        if (response.ok) {
            const data = await response.json();
            appState.maxUploadSizeMb = finiteNumber(data.max_upload_size_mb, 25);
            
            // Atualiza o modo AI
            if (data.ai_mode === "llm") {
                dom.systemModeBadge.innerText = `AI Mode: Claude (${data.llm_model})`;
                dom.systemModeBadge.className = "badge badge-info";
            } else {
                dom.systemModeBadge.innerText = "AI Mode: Heurística Offline";
                dom.systemModeBadge.className = "badge badge-warning";
            }
            
            // Status do Servidor
            if (data.status === "healthy") {
                dom.systemStatusBadge.innerText = "Sistema: Online";
                dom.systemStatusBadge.className = "badge badge-success";
            } else {
                dom.systemStatusBadge.innerText = "Sistema: Degradado";
                dom.systemStatusBadge.className = "badge badge-danger";
            }
        }
    } catch (error) {
        console.error("Erro ao buscar status do sistema:", error);
        dom.systemStatusBadge.innerText = "Sistema: Desconectado";
        dom.systemStatusBadge.className = "badge badge-danger";
    }
}

// 2. Buscar Contratos
async function fetchContracts() {
    try {
        const response = await fetch(`${API_BASE}/api/contracts`);
        if (response.ok) {
            appState.contracts = await response.json();
            renderContractsList();
            calculateGlobalMetrics();
        }
    } catch (error) {
        console.error("Erro ao carregar lista de contratos:", error);
        dom.contractsList.innerHTML = `<div class="empty-state error">Erro ao carregar contratos.</div>`;
    }
}

// 3. Buscar Alertas de Renovação
async function fetchUpcomingAlerts() {
    try {
        const response = await fetch(`${API_BASE}/api/alerts/upcoming`);
        if (response.ok) {
            appState.alerts = await response.json();
            renderTimeline();
        }
    } catch (error) {
        console.error("Erro ao buscar alertas da timeline:", error);
        dom.renewalTimeline.innerHTML = `<div class="empty-state">Erro ao carregar timeline de prazos.</div>`;
    }
}

// 4. Detalhes de um Contrato
async function fetchContractDetails(id) {
    try {
        const response = await fetch(`${API_BASE}/api/contracts/${id}`);
        if (response.ok) {
            const contract = await response.json();
            if (appState.selectedContractId === id) {
                renderContractDetails(contract);
                fetchNegotiationSuggestions(id);
            }
            return contract;
        }
    } catch (error) {
        console.error("Erro ao carregar detalhes do contrato:", error);
        alert("Não foi possível carregar os detalhes deste contrato.");
    }
    return null;
}

// 5. Sugestões de Negociação
async function fetchNegotiationSuggestions(id) {
    dom.intelList.innerHTML = `<div class="empty-state">Buscando sugestões...</div>`;
    try {
        const response = await fetch(`${API_BASE}/api/contracts/${id}/negotiation-intel`);
        if (response.ok) {
            const suggestions = await response.json();
            if (appState.selectedContractId === id) renderNegotiationSuggestions(suggestions);
        }
    } catch (error) {
        console.error("Erro ao carregar sugestões de negociação:", error);
        dom.intelList.innerHTML = `<div class="empty-state">Erro ao carregar sugestões.</div>`;
    }
}

// 6. Upload de Contrato
async function handleFileUpload(file) {
    const vendorName = dom.vendorNameInput.value.trim();
    const extension = file.name.includes(".")
        ? `.${file.name.split(".").pop().toLowerCase()}`
        : "";
    const allowedExtensions = new Set([".pdf", ".docx"]);

    if (!allowedExtensions.has(extension)) {
        showUploadValidationError("Apenas arquivos PDF ou DOCX são permitidos.");
        return;
    }

    const maxUploadBytes = appState.maxUploadSizeMb * 1024 * 1024;
    if (file.size > maxUploadBytes) {
        showUploadValidationError(
            `O arquivo excede o limite de ${appState.maxUploadSizeMb} MB.`
        );
        return;
    }
    
    const formData = new FormData();
    formData.append("file", file);
    if (vendorName) {
        formData.append("vendor_name", vendorName);
    }
    
    // Configura a visualização do progresso
    dom.uploadProgressContainer.style.display = "block";
    dom.uploadProgressFill.style.width = "0%";
    dom.uploadStatusText.innerText = "Enviando arquivo...";
    
    let interval = null;
    try {
        // Animação mockada de upload rápida, finalizando com a resposta do servidor
        let width = 0;
        interval = setInterval(() => {
            if (width < 85) {
                width += 5;
                dom.uploadProgressFill.style.width = `${width}%`;
            }
        }, 100);

        const response = await fetch(`${API_BASE}/api/contracts/upload`, {
            method: "POST",
            body: formData
        });
        
        clearInterval(interval);
        
        if (response.ok) {
            const data = await response.json();
            dom.uploadProgressFill.style.width = "100%";
            dom.uploadStatusText.innerText = "Arquivo processado. Iniciando análise LangGraph...";
            
            // Limpa o input do fornecedor
            dom.vendorNameInput.value = "";
            
            // Espera 1.5s e esconde o loader, recarregando a lista
            setTimeout(() => {
                dom.uploadProgressContainer.style.display = "none";
                fetchContracts();
                fetchUpcomingAlerts();
                
                // Seleciona automaticamente o contrato recém enviado
                selectContractItem(data.contract_id);
                pollAnalysisUntilTerminal(data.contract_id);
            }, 1500);
        } else {
            const errData = await response.json();
            throw new Error(errData.detail || "Erro no upload.");
        }
    } catch (error) {
        if (interval) clearInterval(interval);
        console.error("Erro no upload:", error);
        dom.uploadProgressFill.style.backgroundColor = "var(--color-high-risk)";
        dom.uploadStatusText.innerText = `Erro: ${error.message}`;
        setTimeout(() => {
            dom.uploadProgressContainer.style.display = "none";
            dom.uploadProgressFill.style.backgroundColor = "var(--color-primary)";
        }, 5000);
    }
}

function showUploadValidationError(message) {
    dom.uploadProgressContainer.style.display = "block";
    dom.uploadProgressFill.style.width = "0%";
    dom.uploadProgressFill.style.backgroundColor = "var(--color-high-risk)";
    dom.uploadStatusText.innerText = message;
    setTimeout(() => {
        dom.uploadProgressContainer.style.display = "none";
        dom.uploadProgressFill.style.backgroundColor = "var(--color-primary)";
    }, 5000);
}

// 7. Reanalisar Contrato
async function triggerReanalysis(id) {
    dom.btnReanalyze.disabled = true;
    dom.btnReanalyze.innerText = "🔄 Analisando...";
    
    try {
        const response = await fetch(`${API_BASE}/api/contracts/${id}/analyze`, {
            method: "POST"
        });
        
        if (response.ok) {
            await fetchContracts();
            await fetchContractDetails(id);
            await pollAnalysisUntilTerminal(id);
        } else {
            const payload = await response.json().catch(() => ({}));
            throw new Error(payload.detail || "Erro ao disparar análise.");
        }
    } catch (error) {
        console.error(error);
        alert(error.message || "Erro ao disparar reanálise contratual.");
        if (appState.selectedContractId === id) await fetchContractDetails(id);
    }
}

async function pollAnalysisUntilTerminal(id) {
    if (appState.pollingContracts.has(id)) return null;
    appState.pollingContracts.add(id);
    const runningStatuses = new Set(["queued", "processing"]);
    try {
        while (appState.selectedContractId === id) {
            const contract = await fetchContractDetails(id);
            await fetchContracts();
            if (!contract || !runningStatuses.has(contract.analysis_status)) {
                await fetchUpcomingAlerts();
                await fetchValueLeakage();
                return contract;
            }
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    } finally {
        appState.pollingContracts.delete(id);
    }
    return null;
}

// 7.1 Terminate Contrato
async function triggerTermination(id) {
    dom.btnTerminate.disabled = true;
    dom.btnTerminate.innerText = "Gerando Email...";
    
    try {
        const response = await fetch(`${API_BASE}/api/contracts/${id}/terminate`, {
            method: "POST"
        });
        
        if (response.ok) {
            const data = await response.json();
            // Abre o cliente de email do usuário
            if (typeof data.mailto !== "string" || !data.mailto.startsWith("mailto:")) {
                throw new Error("Resposta de cancelamento inválida.");
            }
            window.location.href = data.mailto;
        } else {
            alert("Erro ao gerar cancelamento.");
        }
    } catch (error) {
        console.error(error);
        alert("Erro na rede ao tentar gerar o cancelamento.");
    } finally {
        dom.btnTerminate.disabled = false;
        dom.btnTerminate.innerText = "🛑 1-Click Terminate";
    }
}

// 8. Resolver Alerta
async function resolveAlert(alertId, eventCard) {
    try {
        const response = await fetch(`${API_BASE}/api/alerts/${alertId}/resolve`, {
            method: "PATCH"
        });
        
        if (response.ok) {
            // Efeito visual de esmaecimento do card
            eventCard.style.opacity = "0";
            eventCard.style.transform = "scale(0.9)";
            setTimeout(() => {
                fetchUpcomingAlerts();
                fetchContracts(); // atualiza status se mudou para cancelado
            }, 300);
        }
    } catch (error) {
        console.error("Erro ao resolver alerta:", error);
    }
}

// 9. Q&A Chat
async function submitQuestion() {
    const question = dom.chatInput.value.trim();
    if (!question || !appState.selectedContractId) return;
    
    // Adiciona pergunta na tela
    appendChatMessage(question, "user-msg");
    dom.chatInput.value = "";
    
    // Indicador de carregamento
    const loaderId = appendChatMessage("Digitando resposta...", "ai-msg typing-msg");
    
    try {
        const response = await fetch(`${API_BASE}/api/negotiation/ask`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                contract_id: appState.selectedContractId,
                question: question
            })
        });
        
        // Remove o indicador de carregamento
        const loaderElem = document.getElementById(loaderId);
        if (loaderElem) loaderElem.remove();
        
        if (response.ok) {
            const data = await response.json();
            appendChatMessage(data.response, "ai-msg");
        } else {
            const data = await response.json().catch(() => ({}));
            appendChatMessage(data.detail || "Erro ao consultar o assistente.", "ai-msg");
        }
    } catch (error) {
        console.error(error);
        const loaderElem = document.getElementById(loaderId);
        if (loaderElem) loaderElem.remove();
        appendChatMessage("Erro de rede. Verifique se o servidor está ativo.", "ai-msg");
    }
}

// --- MÉTODOS DE RENDERIZAÇÃO ---

// Renderiza a Lista de Contratos na Sidebar
function renderContractsList() {
    dom.contractsList.innerHTML = "";
    
    const filtered = appState.contracts.filter(c => {
        if (!appState.statusFilter) return true;
        return c.status === appState.statusFilter;
    });
    
    dom.contractsCount.innerText = filtered.length;
    
    if (filtered.length === 0) {
        dom.contractsList.innerHTML = `<div class="empty-state">Nenhum contrato encontrado.</div>`;
        return;
    }
    
    filtered.forEach(c => {
        const item = document.createElement("div");
        item.className = `contract-item ${appState.selectedContractId === c.id ? "selected" : ""}`;
        item.dataset.id = c.id;

        const rawScore = optionalFiniteNumber(c.health_score);
        const score = rawScore === null ? null : Math.min(100, Math.max(0, rawScore));
        const scoreClass = score === null ? "score-unknown" : getHealthScoreClass(score);
        const scoreLabel = score === null ? "—" : score.toFixed(1);
        
        item.innerHTML = `
            <div class="contract-info">
                <span class="contract-name" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span>
                <span class="contract-vendor">${escapeHtml(c.vendor_name)}</span>
            </div>
            <div class="contract-meta">
                <span class="score-badge ${scoreClass}">${scoreLabel}</span>
                <span class="badge ${getStatusBadgeClass(c.status)}">${escapeHtml(c.status)}</span>
                <span class="badge ${getAnalysisStatusBadgeClass(c.analysis_status)}">${escapeHtml(getAnalysisStatusLabel(c.analysis_status))}</span>
            </div>
        `;
        
        item.addEventListener("click", () => selectContractItem(c.id));
        dom.contractsList.appendChild(item);
    });
}

function selectContractItem(id) {
    appState.selectedContractId = id;
    
    // Atualiza a seleção visual
    document.querySelectorAll(".contract-item").forEach(item => {
        if (parseInt(item.dataset.id) === id) {
            item.classList.add("selected");
        } else {
            item.classList.remove("selected");
        }
    });
    
    // Exibe o painel de detalhes e oculta as boas-vindas
    dom.welcomePanel.style.display = "none";
    dom.detailsViewer.style.display = "block";
    
    // Limpa chat
    dom.chatBox.innerHTML = `
        <div class="message system-msg">
            Olá! Pergunte-me qualquer dúvida sobre este contrato. Por exemplo: "Posso rescindir este contrato sem pagar multa?" ou "Qual o prazo de aviso prévio para cancelamento?"
        </div>
    `;
    
    pollAnalysisUntilTerminal(id);
}

// Renderiza a Ficha de Detalhes do Contrato
function renderContractDetails(c) {
    dom.viewContractTitle.innerText = c.title;
    dom.viewContractVendor.innerText = `Fornecedor: ${c.vendor_name}`;
    
    // Configura o link para abrir o PDF real
    dom.btnOpenPdf.href = `${API_BASE}/api/contracts/${c.id}/file`;
    
    // Dados e vigência
    dom.viewContractStatus.innerText = c.status;
    dom.viewContractStatus.className = `badge ${getStatusBadgeClass(c.status)}`;

    dom.viewAnalysisStatus.innerText = getAnalysisStatusLabel(c.analysis_status);
    dom.viewAnalysisStatus.className = `badge ${getAnalysisStatusBadgeClass(c.analysis_status)}`;
    const analysisRunning = ["queued", "processing"].includes(c.analysis_status);
    dom.btnReanalyze.disabled = analysisRunning;
    dom.btnReanalyze.innerText = analysisRunning ? "🔄 Analisando..." : "🔄 Reanalisar";

    const analysisMessages = [];
    if (c.analysis_error) analysisMessages.push(c.analysis_error);
    if (["failed", "needs_review"].includes(c.analysis_status) && finiteNumber(c.analysis_revision, 0) > 0) {
        analysisMessages.push("Os resultados exibidos pertencem à última análise concluída com sucesso.");
    }
    if (Array.isArray(c.analysis_warnings) && c.analysis_warnings.length > 0) {
        analysisMessages.push(`Avisos: ${c.analysis_warnings.map(formatAnalysisWarning).join("; ")}`);
    }
    dom.analysisMessage.innerText = analysisMessages.join(" ");
    dom.analysisMessage.style.display = analysisMessages.length > 0 ? "block" : "none";
    const hasCompletedAnalysis = finiteNumber(c.analysis_revision, 0) > 0;
    dom.chatInput.disabled = !hasCompletedAnalysis;
    dom.btnSendChat.disabled = !hasCompletedAnalysis;
    dom.chatInput.placeholder = hasCompletedAnalysis
        ? "Digite sua pergunta aqui..."
        : "Conclua a análise antes de usar o Q&A";
    
    const rawHealthScore = optionalFiniteNumber(c.health_score);
    const healthScore = rawHealthScore === null
        ? null
        : Math.min(100, Math.max(0, rawHealthScore));
    dom.viewContractHealth.innerText = healthScore === null ? "Não disponível" : healthScore.toFixed(1);
    dom.viewContractHealth.className = `score-badge ${healthScore === null ? "score-unknown" : getHealthScoreClass(healthScore)}`;
    
    dom.viewContractStartDate.innerText = formatDate(c.start_date);
    dom.viewContractEndDate.innerText = formatDate(c.end_date);
    dom.viewContractAutorenew.innerText = c.auto_renews === null
        ? "Não identificado"
        : (c.auto_renews ? "Sim" : "Não");
    dom.viewContractNoticeDays.innerText = c.renewal_notice_days === null
        ? "Não identificado"
        : `${c.renewal_notice_days} dias`;
    
    // Valor financeiro
    if (c.financial_value !== null) {
        dom.viewContractValue.innerText = formatCurrency(c.financial_value, c.financial_currency);
    } else {
        dom.viewContractValue.innerText = "Não especificado";
    }
    dom.viewContractFrequency.innerText = c.payment_frequency ? c.payment_frequency.toUpperCase() : "-";
    
    // Renderiza as cláusulas
    renderClausesList(c.clauses);
    renderEvidenceList(c.analysis_evidence);
    
    // O score de cláusulas não comprova a situação cadastral do fornecedor.
    dom.viewVendorRisk.style.display = "none";
}

// Renderiza a Lista de Cláusulas Extraídas
function renderClausesList(clauses) {
    dom.clausesList.innerHTML = "";
    
    if (!clauses || clauses.length === 0) {
        dom.clausesList.innerHTML = `<div class="empty-state">Nenhuma cláusula crítica identificada. Reprocesse o contrato.</div>`;
        return;
    }
    
    clauses.forEach(cl => {
        const card = document.createElement("div");
        const riskLevel = ["low", "medium", "high"].includes(cl.risk_level)
            ? cl.risk_level
            : "unknown";
        card.className = `clause-card risk-${riskLevel}`;
        
        card.innerHTML = `
            <div class="clause-header">
                <span class="clause-name">${escapeHtml(cl.clause_type)}</span>
                <span class="badge ${getStatusBadgeClassByRisk(riskLevel)}">${escapeHtml(riskLevel)}</span>
            </div>
            <div class="clause-summary">${escapeHtml(cl.summary || "Sem resumo.")}</div>
            ${cl.risk_explanation ? `<div class="clause-explanation"><strong>Risco:</strong> ${escapeHtml(cl.risk_explanation)}</div>` : ""}
            <div class="clause-text">"${escapeHtml(cl.original_text)}"</div>
        `;
        
        dom.clausesList.appendChild(card);
    });
}

function renderEvidenceList(evidence) {
    dom.evidenceList.innerHTML = "";
    if (!Array.isArray(evidence) || evidence.length === 0) {
        dom.evidenceList.innerHTML = `<div class="empty-state">Nenhuma evidência estruturada disponível.</div>`;
        return;
    }

    evidence.forEach(item => {
        const card = document.createElement("div");
        card.className = "evidence-card";
        const confidence = optionalFiniteNumber(item.confidence);
        const confidenceLabel = confidence === null
            ? ""
            : ` · confiança ${(confidence * 100).toFixed(0)}%`;
        card.innerHTML = `
            <div class="evidence-field">${escapeHtml(formatEvidenceField(item.field_name))}</div>
            <div class="evidence-value">${escapeHtml(item.normalized_value ?? "")}${escapeHtml(confidenceLabel)}</div>
            <blockquote class="evidence-source">${escapeHtml(item.source_text)}</blockquote>
        `;
        dom.evidenceList.appendChild(card);
    });
}

// Renderiza as Sugestões de Negociação
function renderNegotiationSuggestions(suggestions) {
    dom.intelList.innerHTML = "";
    
    if (!suggestions || suggestions.length === 0) {
        dom.intelList.innerHTML = `<div class="empty-state">Nenhuma sugestão disponível nesta análise.</div>`;
        return;
    }
    
    suggestions.forEach(s => {
        const card = document.createElement("div");
        card.className = "intel-card";
        
        card.innerHTML = `
            <div class="intel-type">💡 ${escapeHtml(s.benchmark_type)}</div>
            <div class="intel-rate"><strong>Prazo de Mercado:</strong> ${escapeHtml(s.market_rate)}</div>
            <div class="intel-suggestion"><strong>Recomendação:</strong> ${escapeHtml(s.suggestion)}</div>
        `;
        
        dom.intelList.appendChild(card);
    });
}

// Renderiza a Timeline de Alertas
function renderTimeline() {
    dom.renewalTimeline.innerHTML = "";
    
    if (appState.alerts.length === 0) {
        dom.renewalTimeline.innerHTML = `<div class="empty-state">Nenhum alerta de prazo ativo na timeline.</div>`;
        return;
    }
    
    appState.alerts.forEach(a => {
        const card = document.createElement("div");
        card.className = "timeline-event";
        
        let alertTypeLabel = "Expiração";
        if (a.alert_type === "renewal_90d") alertTypeLabel = "Cancelamento (90d)";
        else if (a.alert_type === "renewal_60d") alertTypeLabel = "Cancelamento (60d)";
        else if (a.alert_type === "renewal_30d") alertTypeLabel = "Cancelamento (30d)";
        else if (a.alert_type === "expiration_90d") alertTypeLabel = "Expiração (90d)";
        else if (a.alert_type === "expiration_60d") alertTypeLabel = "Expiração (60d)";
        else if (a.alert_type === "expiration_30d") alertTypeLabel = "Expiração (30d)";
        
        card.innerHTML = `
            <div class="event-date">⏰ Alerta: ${escapeHtml(formatDate(a.trigger_date))}</div>
            <div class="event-type font-highlight">${alertTypeLabel}</div>
            <div class="event-title" title="${escapeHtml(a.contract_title)}">${escapeHtml(a.contract_title)}</div>
            <div class="event-vendor">${escapeHtml(a.vendor_name)}</div>
            <button class="btn btn-secondary btn-resolve-alert">Resolver Alerta</button>
        `;
        
        // Evento para resolver alerta
        card.querySelector(".btn-resolve-alert").addEventListener("click", () => {
            resolveAlert(a.id, card);
        });
        
        dom.renewalTimeline.appendChild(card);
    });
}

// --- MÉTODOS AUXILIARES ---

// Adiciona mensagem no painel de chat e dá scroll
function appendChatMessage(text, className) {
    const id = `msg-${Date.now()}`;
    const msg = document.createElement("div");
    msg.className = `message ${className}`;
    msg.id = id;
    msg.innerText = text;
    dom.chatBox.appendChild(msg);
    dom.chatBox.scrollTop = dom.chatBox.scrollHeight;
    return id;
}

// Calcula Métricas Consolidadas do Portfólio
function calculateGlobalMetrics() {
    if (appState.contracts.length === 0) {
        dom.avgHealthScore.innerText = "—";
        dom.avgHealthBar.style.width = "0%";
        dom.criticalContractsCount.innerText = "0";
        dom.criticalContractsPct.innerText = "0% do portfólio";
        dom.totalFinancialValue.innerText = "—";
        return;
    }
    
    // Métricas de saúde incluem apenas análises concluídas e versionadas.
    const analyzedContracts = appState.contracts.filter(c =>
        finiteNumber(c.analysis_revision, 0) > 0 && optionalFiniteNumber(c.health_score) !== null
    );
    if (analyzedContracts.length > 0) {
        const totalHealth = analyzedContracts.reduce(
            (sum, c) => sum + Math.min(100, Math.max(0, optionalFiniteNumber(c.health_score))),
            0
        );
        const avgScore = totalHealth / analyzedContracts.length;
        dom.avgHealthScore.innerText = avgScore.toFixed(1);
        dom.avgHealthBar.style.width = `${avgScore}%`;
    } else {
        dom.avgHealthScore.innerText = "—";
        dom.avgHealthBar.style.width = "0%";
    }
    
    // Contratos Críticos (health_score < 70)
    const criticalContracts = analyzedContracts.filter(
        c => optionalFiniteNumber(c.health_score) < 70
    );
    const criticalCount = criticalContracts.length;
    const criticalPct = analyzedContracts.length > 0
        ? Math.round((criticalCount / analyzedContracts.length) * 100)
        : 0;
    dom.criticalContractsCount.innerText = criticalCount;
    dom.criticalContractsPct.innerText = `${criticalPct}% dos analisados`;
    
    // Total Financeiro Mapeado
    const totalsByCurrency = new Map();
    appState.contracts.forEach(c => {
        if (
            finiteNumber(c.analysis_revision, 0) > 0 &&
            c.financial_value !== null &&
            typeof c.financial_currency === "string"
        ) {
            const current = totalsByCurrency.get(c.financial_currency) || 0;
            totalsByCurrency.set(
                c.financial_currency,
                current + finiteNumber(c.financial_value, 0)
            );
        }
    });
    if (totalsByCurrency.size === 1) {
        const [currency, total] = totalsByCurrency.entries().next().value;
        dom.totalFinancialValue.innerText = formatCurrency(total, currency);
        dom.totalFinancialValue.title = "";
    } else if (totalsByCurrency.size > 1) {
        dom.totalFinancialValue.innerText = "Múltiplas moedas";
        dom.totalFinancialValue.title = Array.from(totalsByCurrency.entries())
            .map(([currency, total]) => formatCurrency(total, currency))
            .join(" · ");
    } else {
        dom.totalFinancialValue.innerText = "—";
        dom.totalFinancialValue.title = "";
    }
}

// Helper para classes CSS de badges baseadas no status
function getStatusBadgeClass(status) {
    switch (status) {
        case "active": return "badge-success";
        case "draft": return "badge-info";
        case "expired": return "badge-warning";
        case "terminated": return "badge-danger";
        default: return "badge-secondary";
    }
}

function getAnalysisStatusBadgeClass(status) {
    switch (status) {
        case "completed": return "badge-success";
        case "queued":
        case "processing": return "badge-info";
        case "needs_review": return "badge-warning";
        case "failed": return "badge-danger";
        default: return "badge-secondary";
    }
}

function getAnalysisStatusLabel(status) {
    const labels = {
        not_started: "Não analisado",
        queued: "Na fila",
        processing: "Analisando",
        completed: "Análise concluída",
        needs_review: "Revisão necessária",
        failed: "Análise falhou",
        legacy: "Legado não auditado",
    };
    return labels[status] || "Estado desconhecido";
}

function formatEvidenceField(fieldName) {
    const labels = {
        financial_value: "Valor financeiro",
        financial_currency: "Moeda",
        payment_frequency: "Frequência de pagamento",
        start_date: "Data de início",
        end_date: "Data de término",
        auto_renews: "Renovação automática",
        renewal_notice_days: "Prazo de aviso",
    };
    return labels[fieldName] || fieldName || "Campo";
}

function formatAnalysisWarning(code) {
    const labels = {
        EXTRACTED_TEXT_TRUNCATED: "texto truncado no limite configurado",
        NO_TARGET_CLAUSES_FOUND: "nenhuma cláusula-alvo foi localizada",
        FINANCIAL_VALUE_NOT_FOUND: "valor financeiro não identificado",
        MULTIPLE_FINANCIAL_VALUES_FOUND: "múltiplos valores encontrados; o contexto mais relevante foi selecionado",
        PAYMENT_FREQUENCY_NOT_FOUND: "frequência de pagamento não identificada",
        MULTIPLE_PAYMENT_FREQUENCIES_FOUND: "múltiplas frequências de pagamento encontradas",
        CONTRACT_DATES_NOT_FOUND: "datas contratuais não identificadas",
        CONTRACT_DATES_NOT_CONTEXTUALIZED: "datas encontradas sem função contratual inequívoca",
        AMBIGUOUS_NUMERIC_DATE_IGNORED: "data numérica ambígua ignorada",
        AUTO_RENEWAL_NOT_FOUND: "renovação automática não identificada",
        NOTICE_PERIOD_NOT_FOUND: "prazo de aviso não identificado",
        RENEWAL_DEADLINE_UNAVAILABLE: "prazo de renovação indisponível sem aviso expresso",
    };
    return labels[code] || code;
}

// Helper para classes CSS de badges baseadas no nível de risco
function getStatusBadgeClassByRisk(risk) {
    switch (risk) {
        case "low": return "badge-success";
        case "medium": return "badge-warning";
        case "high": return "badge-danger";
        default: return "badge-secondary";
    }
}

// Helper para classes CSS de score
function getHealthScoreClass(score) {
    if (score < 50) return "score-low";
    if (score < 80) return "score-medium";
    return "score-high";
}

// Formatar data de YYYY-MM-DD para DD/MM/YYYY
function formatDate(dateStr) {
    if (!dateStr) return "-";
    try {
        const parts = dateStr.split("-");
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return dateStr;
    } catch (e) {
        return dateStr;
    }
}

// Formatar valor sem atribuir uma moeda que não foi extraída do contrato.
function formatCurrency(val, currency) {
    if (!currency || !["USD", "BRL"].includes(currency)) {
        return `${finiteNumber(val, 0).toFixed(2)} (moeda não identificada)`;
    }
    const locale = currency === "BRL" ? "pt-BR" : "en-US";
    return new Intl.NumberFormat(locale, {
        style: "currency",
        currency: currency
    }).format(finiteNumber(val, 0));
}

let leakageChartInstance = null;

async function fetchValueLeakage() {
    try {
        const response = await fetch(`${API_BASE}/api/analysis/value-leakage`);
        if (response.ok) {
            const data = await response.json();
            renderValueLeakageChart(data);
        }
    } catch (e) {
        console.error("Erro ao buscar value leakage", e);
    }
}

function renderValueLeakageChart(data) {
    const ctx = document.getElementById('leakageChart').getContext('2d');
    
    if (leakageChartInstance) {
        leakageChartInstance.destroy();
    }
    
    const labels = [...new Set(data.map(d => String(d.month ?? "")))];
    const currencies = [...new Set(data.map(d => String(d.currency ?? "")))];
    const colors = [
        ["rgba(239, 68, 68, 0.7)", "rgb(239, 68, 68)"],
        ["rgba(59, 130, 246, 0.7)", "rgb(59, 130, 246)"],
        ["rgba(245, 158, 11, 0.7)", "rgb(245, 158, 11)"],
    ];
    const datasets = currencies.map((currency, index) => ({
        label: `Value at Risk (${currency})`,
        data: labels.map(month => {
            const row = data.find(item => item.month === month && item.currency === currency);
            return row ? finiteNumber(row.total_value, 0) : 0;
        }),
        backgroundColor: colors[index % colors.length][0],
        borderColor: colors[index % colors.length][1],
        borderWidth: 1,
        borderRadius: 4,
    }));
    
    leakageChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: currencies.length > 1 },
                tooltip: {
                    callbacks: {
                        label: context => formatCurrency(
                            context.parsed.y,
                            currencies[context.datasetIndex]
                        )
                    }
                }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
}
