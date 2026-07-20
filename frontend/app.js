// app.js — Lógica do painel VEGA

// Estado Global da Aplicação
const appState = {
    contracts: [],
    selectedContractId: null,
    alerts: [],
    statusFilter: "",
};

// URL Base da API (vazio se servido localmente a partir da raiz do FastAPI)
const API_BASE = "";

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
            renderContractDetails(contract);
            fetchNegotiationSuggestions(id);
        }
    } catch (error) {
        console.error("Erro ao carregar detalhes do contrato:", error);
        alert("Não foi possível carregar os detalhes deste contrato.");
    }
}

// 5. Sugestões de Negociação
async function fetchNegotiationSuggestions(id) {
    dom.intelList.innerHTML = `<div class="empty-state">Buscando sugestões...</div>`;
    try {
        const response = await fetch(`${API_BASE}/api/contracts/${id}/negotiation-intel`);
        if (response.ok) {
            const suggestions = await response.json();
            renderNegotiationSuggestions(suggestions);
        }
    } catch (error) {
        console.error("Erro ao carregar sugestões de negociação:", error);
        dom.intelList.innerHTML = `<div class="empty-state">Erro ao carregar sugestões.</div>`;
    }
}

// 6. Upload de Contrato
async function handleFileUpload(file) {
    const vendorName = dom.vendorNameInput.value.trim();
    
    const formData = new FormData();
    formData.append("file", file);
    if (vendorName) {
        formData.append("vendor_name", vendorName);
    }
    
    // Configura a visualização do progresso
    dom.uploadProgressContainer.style.display = "block";
    dom.uploadProgressFill.style.width = "0%";
    dom.uploadStatusText.innerText = "Enviando arquivo...";
    
    try {
        // Animação mockada de upload rápida, finalizando com a resposta do servidor
        let width = 0;
        const interval = setInterval(() => {
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
            }, 1500);
        } else {
            const errData = await response.json();
            throw new Error(errData.detail || "Erro no upload.");
        }
    } catch (error) {
        console.error("Erro no upload:", error);
        dom.uploadProgressFill.style.backgroundColor = "var(--color-high-risk)";
        dom.uploadStatusText.innerText = `Erro: ${error.message}`;
        setTimeout(() => {
            dom.uploadProgressContainer.style.display = "none";
            dom.uploadProgressFill.style.backgroundColor = "var(--color-primary)";
        }, 5000);
    }
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
            // A análise roda em background. Vamos dar um delay e recarregar
            setTimeout(async () => {
                await fetchContracts();
                await fetchContractDetails(id);
                await fetchUpcomingAlerts();
                dom.btnReanalyze.disabled = false;
                dom.btnReanalyze.innerText = "🔄 Reanalisar";
            }, 3000);
        } else {
            throw new Error("Erro ao disparar análise.");
        }
    } catch (error) {
        console.error(error);
        alert("Erro ao disparar reanálise contratual.");
        dom.btnReanalyze.disabled = false;
        dom.btnReanalyze.innerText = "🔄 Reanalisar";
    }
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
            appendChatMessage("Desculpe, ocorreu um erro ao consultar o assistente.", "ai-msg");
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
        
        let scoreClass = "score-high";
        if (c.health_score < 50) scoreClass = "score-low";
        else if (c.health_score < 80) scoreClass = "score-medium";
        
        item.innerHTML = `
            <div class="contract-info">
                <span class="contract-name" title="${c.title}">${c.title}</span>
                <span class="contract-vendor">${c.vendor_name}</span>
            </div>
            <div class="contract-meta">
                <span class="score-badge ${scoreClass}">${c.health_score.toFixed(1)}</span>
                <span class="badge ${getStatusBadgeClass(c.status)}">${c.status}</span>
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
    
    fetchContractDetails(id);
}

// Renderiza a Ficha de Detalhes do Contrato
function renderContractDetails(c) {
    dom.viewContractTitle.innerText = c.title;
    dom.viewContractVendor.innerText = `Fornecedor: ${c.vendor_name}`;
    
    // Configura o link para abrir o PDF real
    dom.btnOpenPdf.href = `/${c.file_path}`;
    
    // Dados e vigência
    dom.viewContractStatus.innerText = c.status;
    dom.viewContractStatus.className = `badge ${getStatusBadgeClass(c.status)}`;
    
    dom.viewContractHealth.innerText = c.health_score.toFixed(1);
    dom.viewContractHealth.className = `score-badge ${getHealthScoreClass(c.health_score)}`;
    
    dom.viewContractStartDate.innerText = formatDate(c.start_date);
    dom.viewContractEndDate.innerText = formatDate(c.end_date);
    dom.viewContractAutorenew.innerText = c.auto_renews ? "Sim" : "Não";
    dom.viewContractNoticeDays.innerText = `${c.renewal_notice_days} dias`;
    
    // Valor financeiro
    if (c.financial_value !== null) {
        dom.viewContractValue.innerText = formatCurrency(c.financial_value);
    } else {
        dom.viewContractValue.innerText = "Não especificado";
    }
    dom.viewContractFrequency.innerText = c.payment_frequency ? c.payment_frequency.toUpperCase() : "-";
    
    // Renderiza as cláusulas
    renderClausesList(c.clauses);
    
    // Atualiza Risk Badge se OFAC foi mapeado (aqui o payload teria de retornar ofac_status, mas se não tiver, defaultamos)
    // Se precisarmos que o status real venha, seria ideal adicionar no backend, para este protótipo vamos simular
    // base no health_score ou se a chave vier na API. 
    dom.viewVendorRisk.style.display = "inline-block";
    if (c.health_score < 70) {
        dom.viewVendorRisk.innerText = "Risk: Elevated";
        dom.viewVendorRisk.className = "badge badge-danger";
    } else {
        dom.viewVendorRisk.innerText = "Risk: Clear";
        dom.viewVendorRisk.className = "badge badge-success";
    }
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
        card.className = `clause-card risk-${cl.risk_level}`;
        
        card.innerHTML = `
            <div class="clause-header">
                <span class="clause-name">${cl.clause_type}</span>
                <span class="badge ${getStatusBadgeClassByRisk(cl.risk_level)}">${cl.risk_level}</span>
            </div>
            <div class="clause-summary">${cl.summary || "Sem resumo."}</div>
            ${cl.risk_explanation ? `<div class="clause-explanation"><strong>Risco:</strong> ${cl.risk_explanation}</div>` : ""}
            <div class="clause-text">"${cl.original_text}"</div>
        `;
        
        dom.clausesList.appendChild(card);
    });
}

// Renderiza as Sugestões de Negociação
function renderNegotiationSuggestions(suggestions) {
    dom.intelList.innerHTML = "";
    
    if (!suggestions || suggestions.length === 0) {
        dom.intelList.innerHTML = `<div class="empty-state">Nenhuma sugestão necessária (contrato de baixo risco).</div>`;
        return;
    }
    
    suggestions.forEach(s => {
        const card = document.createElement("div");
        card.className = "intel-card";
        
        card.innerHTML = `
            <div class="intel-type">💡 ${s.benchmark_type}</div>
            <div class="intel-rate"><strong>Prazo de Mercado:</strong> ${s.market_rate}</div>
            <div class="intel-suggestion"><strong>Recomendação:</strong> ${s.suggestion}</div>
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
        
        card.innerHTML = `
            <div class="event-date">⏰ Alerta: ${formatDate(a.trigger_date)}</div>
            <div class="event-type font-highlight">${alertTypeLabel}</div>
            <div class="event-title" title="${a.contract_title}">${a.contract_title}</div>
            <div class="event-vendor">${a.vendor_name}</div>
            <button class="btn btn-secondary btn-resolve-alert" data-id="${a.id}">Resolver Alerta</button>
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
        dom.avgHealthScore.innerText = "100.0";
        dom.avgHealthBar.style.width = "100%";
        dom.criticalContractsCount.innerText = "0";
        dom.criticalContractsPct.innerText = "0% do portfólio";
        dom.totalFinancialValue.innerText = "$0.00";
        return;
    }
    
    // Média de Saúde
    const totalHealth = appState.contracts.reduce((sum, c) => sum + c.health_score, 0);
    const avgScore = totalHealth / appState.contracts.length;
    dom.avgHealthScore.innerText = avgScore.toFixed(1);
    dom.avgHealthBar.style.width = `${avgScore}%`;
    
    // Contratos Críticos (health_score < 70)
    const criticalContracts = appState.contracts.filter(c => c.health_score < 70);
    const criticalCount = criticalContracts.length;
    const criticalPct = Math.round((criticalCount / appState.contracts.length) * 100);
    dom.criticalContractsCount.innerText = criticalCount;
    dom.criticalContractsPct.innerText = `${criticalPct}% do portfólio`;
    
    // Total Financeiro Mapeado
    const totalVal = appState.contracts.reduce((sum, c) => {
        if (c.financial_value) return sum + c.financial_value;
        return sum;
    }, 0);
    dom.totalFinancialValue.innerText = formatCurrency(totalVal);
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

// Formatar valor para Moeda Dólar
function formatCurrency(val) {
    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD"
    }).format(val);
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
    
    const labels = data.map(d => d.month);
    const values = data.map(d => d.total_value);
    
    leakageChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Value at Risk ($)',
                data: values,
                backgroundColor: 'rgba(239, 68, 68, 0.7)',
                borderColor: 'rgb(239, 68, 68)',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
}
