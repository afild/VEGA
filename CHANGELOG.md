# Changelog — VEGA (Vendor & Contract Governance Agent)

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
e este projeto adere ao versionamento semântico.

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
