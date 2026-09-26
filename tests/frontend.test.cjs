const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function dashboard() {
    const nodes = new Map();
    const element = () => ({
        innerText: '', innerHTML: '', style: {}, children: [],
        appendChild(child) { this.children.push(child); },
        addEventListener() {},
    });
    const context = vm.createContext({
        console, Intl, setTimeout, clearTimeout, setInterval, clearInterval,
        alert: () => {},
        document: {
            addEventListener() {},
            getElementById(id) {
                if (!nodes.has(id)) nodes.set(id, element());
                return nodes.get(id);
            },
            createElement: element,
        },
    });
    vm.runInContext(readFileSync(join(__dirname, '../frontend/app.js'), 'utf8'), context);
    return { context, nodes, run: code => vm.runInContext(code, context) };
}

test('pending documents have no health score and cannot use Q&A', () => {
    const ui = dashboard();
    ui.run(`renderContractDetails({id: 1, title: 'Scanned', status: 'draft',
        analysis_status: 'needs_review', analysis_revision: 0, health_score: null,
        auto_renews: null, renewal_notice_days: null, financial_value: null});`);
    assert.equal(ui.nodes.get('view-contract-health').innerText, 'Não disponível');
    assert.equal(ui.nodes.get('btn-send-chat').disabled, true);
    assert.equal(ui.nodes.get('view-contract-autorenew').innerText, 'Não identificado');
    assert.equal(ui.nodes.get('view-vendor-risk').style.display, 'none');
});

test('portfolio excludes pending scores and preserves separate currency totals', () => {
    const ui = dashboard();
    ui.run(`appState.contracts = [
        {analysis_revision: 0, health_score: 100, financial_value: 10000, financial_currency: 'USD'},
        {analysis_revision: 1, health_score: 50, financial_value: 100, financial_currency: 'USD'},
        {analysis_revision: 1, health_score: null, financial_value: 200, financial_currency: 'BRL'}
    ]; calculateGlobalMetrics();`);
    assert.equal(ui.nodes.get('avg-health-score').innerText, '50.0');
    assert.equal(ui.nodes.get('critical-contracts-pct').innerText, '100% dos analisados');
    assert.equal(ui.nodes.get('total-financial-value').innerText, 'Múltiplas moedas');
    assert.match(ui.nodes.get('total-financial-value').title, /100/);
    assert.doesNotMatch(ui.nodes.get('total-financial-value').title, /10,000/);
});

test('late response from another contract cannot replace current details', async () => {
    const ui = dashboard();
    ui.context.fetch = async () => ({ok: true, json: async () => ({id: 1, title: 'Old response'})});
    ui.run('appState.selectedContractId = 2;');
    await ui.run('fetchContractDetails(1)');
    assert.equal(ui.nodes.get('view-contract-title').innerText, '');
});

test('source evidence is rendered as escaped content', () => {
    const ui = dashboard();
    ui.run(`renderEvidenceList([{field_name: 'financial_value', normalized_value: '100',
        source_text: '<img src=x onerror=alert(1)>', confidence: 0.9}]);`);
    const html = ui.nodes.get('evidence-list').children[0].innerHTML;
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /&lt;img/);
});
