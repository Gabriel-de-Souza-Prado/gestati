(() => {
    const form = document.querySelector('#ativo-form');
    if (!form) return;
    const categoria = form.querySelector('[name="categoria"]');
    function atualizarPerfil() {
        const perfil = categoria.selectedOptions[0]?.dataset.perfil || '';
        const computador = ['computador', 'notebook'].includes(perfil);
        document.querySelector('#rede-section').hidden = !computador;
        form.querySelectorAll('[data-profile]').forEach(grupo => {
            grupo.hidden = grupo.disabled = grupo.dataset.profile !== perfil;
        });
        const composicao = document.querySelector('#composicao-section');
        if (composicao) {
            composicao.hidden = !computador;
            composicao.querySelectorAll('input,select,textarea,button').forEach(campo => campo.disabled = !computador);
        }
        window.GestatiFormsets.refresh();
    }
    const garantia = form.querySelector('[name="garantia"]');
    const periodo = document.getElementById('garantia-datas');
    const atualizarGarantia = () => {
        const informada = garantia.value === 'com_garantia';
        periodo.hidden = periodo.disabled = !informada;
        periodo.querySelectorAll('input').forEach(input => input.required = informada);
    };
    garantia.addEventListener('change', atualizarGarantia);
    atualizarGarantia();
    categoria.addEventListener('change', atualizarPerfil);
    atualizarPerfil();
    form.querySelectorAll('[data-adicionar]').forEach(botao => botao.addEventListener('click', () => {
        const grupo = botao.dataset.adicionar;
        const total = form.querySelector(`[name="pecas-${grupo}-TOTAL_FORMS"]`);
        window.GestatiFormsets.add(document.getElementById(`linhas-${grupo}`), total, document.getElementById(`vazio-${grupo}`));
    }));
    const salvar = document.getElementById('criar-especificacao');
    salvar?.addEventListener('click', async () => {
        const mensagem = document.getElementById('nova-mensagem');
        const campos = ['nome', 'tipo', 'capacidade', 'unidade_capacidade', 'descricao'];
        const body = new FormData();
        campos.forEach(campo => body.append(`nova-${campo}`, form.querySelector(`[name="nova-${campo}"]`).value));
        body.append('csrfmiddlewaretoken', form.querySelector('[name="csrfmiddlewaretoken"]').value);
        salvar.disabled = true;
        try {
            const resposta = await fetch(form.dataset.especificacaoUrl, {method:'POST', body, headers:{'Accept':'application/json'}});
            if (resposta.redirected) throw new Error('Sua sessão expirou. Entre novamente para cadastrar a especificação.');
            const dados = await resposta.json();
            if (!resposta.ok) throw new Error(Object.values(dados.erros).flat().join(' '));
            const peca = dados.componente;
            form.querySelectorAll('[data-group]').forEach(grupo => {
                if (!grupo.dataset.tipos.split(',').includes(peca.tipo)) return;
                const selects = [...grupo.querySelectorAll('select[name$="-componente"]')];
                selects.push(grupo.querySelector('template').content.querySelector('select'));
                selects.forEach(select => {
                    if (![...select.options].some(o => o.value === String(peca.pk))) {
                        const opcao = new Option(peca.nome, String(peca.pk));
                        opcao.dataset.tipo = peca.tipo; opcao.dataset.capacidade = peca.capacidade || '';
                        select.add(opcao);
                    }
                });
                const vazio = selects.find(select => select.isConnected && !select.value && !select.closest('[data-formset-row]').hidden);
                if (vazio) vazio.value = String(peca.pk);
            });
            mensagem.textContent = `Especificação disponível: ${peca.nome}. Confira a quantidade e a origem da peça no grupo correspondente.`;
        } catch (erro) {
            mensagem.textContent = erro.message || 'Não foi possível cadastrar a especificação.';
        } finally { salvar.disabled = false; }
    });
})();
