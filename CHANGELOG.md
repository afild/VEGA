# Changelog — VEGA (Vendor & Contract Governance Agent)

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
e este projeto adere ao versionamento semântico.

## [Não lançado]

## [0.3.0] - 2026-09-26

### Confiabilidade
- Estado da análise separado do ciclo de vida do contrato, com `queued`, `processing`, `completed`, `needs_review`, `failed` e identificação explícita de registros legados.
- Histórico versionado em `analysis_runs`, incluindo origem, horários, avisos, erros seguros e quantidade de texto extraído.
- Reserva atômica por contrato e token de execução impedem reanálises concorrentes ou tarefas antigas de sobrescrever resultados mais novos.
- Reanálises bem-sucedidas substituem cláusulas, alertas e sugestões em uma transação; falhas preservam integralmente o último resultado válido.
- PDFs sem texto extraível passam para revisão sem score 100, e execuções interrompidas pelo encerramento do processo são marcadas como falhas no próximo startup.
- Migração incremental adicionada para bancos SQLite existentes, classificando análises anteriores como legado não auditado sem apagar contratos.

### Precisão e auditabilidade
- Evidências de datas, valores, moedas, frequência, renovação e prazo de aviso persistidas com trecho literal, offsets, método e confiança.
- Extração de datas por extenso corrigida para inglês e português; datas numéricas ambíguas são ignoradas em vez de presumir locale.
- Valores financeiros escolhidos pelo contexto contratual, evitando confundir multas e limites de responsabilidade com o valor principal.
- Moedas USD e BRL preservadas; totais e Value Leakage não somam moedas diferentes como se fossem equivalentes.
- Ausência de aviso prévio, renovação ou frequência passa a ser `NULL`/`unknown`, sem defaults inventados.
- Extração heurística de cláusulas agora mantém cada `original_text` como trecho contíguo e verbatim; ocorrências repetidas do mesmo tipo não duplicam a penalização do score.
- Textos truncados exigem revisão; ausência de cláusulas-alvo mantém o score indisponível.
- Reanálise preserva identificadores e resolução dos alertas que continuam válidos.
- Interface acompanha o estado real da execução, bloqueia Q&A antes da primeira análise válida e não atribui score contratual ao fornecedor.
- Layout mantém métricas, gráficos e evidências dentro da tela em resoluções desktop e mobile.

### Segurança
- Uploads validados por tamanho, MIME declarado, assinatura PDF e estrutura interna DOCX, com gravação temporária e promoção atômica.
- Proteções contra ZIP path traversal, expansão excessiva de DOCX, leitura de arquivos fora do storage e exposição de caminhos internos pela API.
- Política same-origin por padrão, validação de Host, bloqueio de mutações cross-site e cabeçalhos de segurança no dashboard/API.
- Saídas dinâmicas do dashboard escapadas para impedir XSS persistente por dados de contratos, cláusulas, alertas ou sugestões.
- Chart.js fixado em versão exata com verificação SRI, e modo debug desativado por padrão.
- Compartilhamento de texto bruto com LLM convertido em opt-in explícito.
- Links `mailto:` codificados e entradas de fornecedor/perguntas limitadas e normalizadas.

### Corrigido
- Inicialização com arquivos `.env` que contêm configurações adicionais de integrações locais.
- Resolução da raiz do projeto, do banco SQLite e do diretório de contratos, incluindo compatibilidade com caminhos legados iniciados por `VEGA/`.
- Montagem do dashboard estático e redirecionamento da rota raiz em instalações limpas.
- Rota de Value Leakage alinhada entre backend e frontend em `/api/analysis/value-leakage`.
- Acesso ao arquivo original por uma rota canônica e restrita ao diretório de contratos.
- Isolamento da suíte de testes para impedir bancos e uploads residuais no repositório.
- Versão retornada pelo endpoint de status alinhada à versão da aplicação.
- Foreign keys do SQLite habilitadas e índices adicionados aos principais relacionamentos e filtros.

## [0.2.0] - 2026-07-20

### Adicionado
- **Ingestão Mágica (Zero Data Entry):** Implementado `email_listener.py` integrado nativamente ao `lifespan` do FastAPI para injetar contratos assincronamente via polling IMAP.
- **Value Leakage & 1-Click Terminate:** Criado endpoint `GET /analysis/value-leakage` e botão no dashboard (integrado com Chart.js e `mailto:`) para projetar perdas financeiras.
- **Vendor Risk Radar (Integração OFAC):** O banco de dados agora possui as colunas de verificação no vendor (`ofac_status`) usando chamadas externas à API pública americana.
- **Notificações Integradas (Slack/Teams):** Inseridos disparos `httpx.post()` no calendário de alertas para notificar 90/60/30 dias antecipadamente.
- **Smart Collaborative Drafting (API do Claude):** Inclusão de `redlining.py` conectando Playbooks salvos à revisão de contratos (via API da Anthropic).

## [0.1.0] - 2026-06-15

### Adicionado
- **Estrutura de pastas base:** Configuração do framework FastAPI com roteadores sob `/api` e agentes sob `/app/agents`.
- **Ingestão de Documentos:** Implementado `document_ingestion.py` usando `PyMuPDF` para leitura eficiente de PDFs e `LlamaIndex` para DOCX.
- **Extração de Cláusulas:** Criado `clause_extraction.py` que utiliza Anthropic Claude via LangChain com fallback heurístico offline (Regex) para extrair cláusulas de Termination, Auto-renewal e Liability Cap.
- **Detecção de Riscos:** Implementado `risk_detector.py` para avaliar avisos prévios excessivos (>60 dias) e isenções unilaterais, calculando o `health_score` do contrato.
- **Impacto Financeiro:** Adicionado `financial_impact.py` com suporte anti-alucinação para mapeamento de valores monetários e frequências de pagamentos contratuais.
- **Agendamento de Alertas:** Criado `alert_calendar.py` para projetar e inserir em banco alertas futuros (90d, 60d, 30d e expiração).
- **Inteligência de Negociação:** Implementado `negotiation_intel.py` com suporte para sugestões de contrapropostas de mercado e Chat RAG Q&A contratual.
- **Orquestrador LangGraph:** Desenvolvido `orchestrator.py` definindo o pipeline em `StateGraph`.
- **Banco de Dados SQLite:** Script DDL puro `schema.sql` e gerenciador `db_manager.py`.
- **Frontend Esmeralda:** Dashboard em HTML5/CSS3/Vanilla JS estilizado com efeitos de glassmorphism premium.
- **Suíte de Testes:** Testes unitários e de integração cobrindo API e agentes.
