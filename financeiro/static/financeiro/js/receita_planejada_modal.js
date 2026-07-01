/**
 * Modal "Gerenciar Receita" — criação e edição via AJAX.
 * Espelha o padrão de despesa_fixa_modais.js para Receitas Planejadas.
 *
 * ARQUITETURA: IIFE preserva estado privado (todasOpcoesCategoriaReceita, receitaIdAtual).
 * Toda interação com DOM dinâmico usa Event Delegation via data-action,
 * sem nenhum onclick inline. Todas as funções públicas estão em window.
 */
(function () {
    'use strict';

    // ── Estado privado ───────────────────────────────────────────
    var todasOpcoesCategoriaReceita = null;
    var receitaIdAtual = null; // null = modo criação; number = modo edição

    // ── Constantes de URL ────────────────────────────────────────
    var URL_CADASTRAR       = '/receitas-planejadas/cadastrar/';
    var URL_EDITAR          = '/receitas-planejadas/{id}/editar/';
    var URL_DETALHES        = '/receitas-planejadas/{id}/detalhes/';
    var URL_EXCLUIR         = '/receitas-planejadas/{id}/excluir/';
    var URL_DESVINCULAR     = '/receitas-planejadas/desvincular/{id}/';
    var URL_BUSCA           = '/api/buscar-transacoes/?tipo=receita&q=';

    // ── Helpers privados ─────────────────────────────────────────

    function getCsrfToken() {
        var input = document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function cacheOpcoesCategoriaReceita() {
        var select = document.getElementById('categoriaNovaReceita');
        if (!select || todasOpcoesCategoriaReceita) return;
        todasOpcoesCategoriaReceita = Array.from(select.querySelectorAll('option')).map(function (opt) {
            return {
                value:   opt.value,
                text:    opt.textContent,
                macroId: opt.getAttribute('data-macro-id'),
            };
        });
    }

    function filtrarCategoriasReceitaPorMacro(macroId, categoriaAtualId) {
        var select = document.getElementById('categoriaNovaReceita');
        if (!select || !todasOpcoesCategoriaReceita) return;

        var macroKey = macroId ? String(macroId) : null;
        select.innerHTML = '';

        var placeholder = document.createElement('option');
        placeholder.value    = '';
        placeholder.disabled = true;
        placeholder.selected = true;
        placeholder.textContent = 'Selecione uma categoria...';
        select.appendChild(placeholder);

        var filtradas = todasOpcoesCategoriaReceita.filter(function (opt) {
            if (!opt.value) return false;
            return macroKey ? opt.macroId === macroKey : true;
        });

        filtradas.forEach(function (opt) {
            var option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.text;
            option.setAttribute('data-macro-id', opt.macroId || '');
            if (categoriaAtualId && String(opt.value) === String(categoriaAtualId)) {
                option.selected = true;
            }
            select.appendChild(option);
        });

        if (filtradas.length === 1 && !categoriaAtualId) {
            select.value = filtradas[0].value;
        }
    }

    function limparCamposReceita() {
        ['receitaNome', 'receitaValor', 'receitaDataInicio', 'receitaDataFim', 'transacaoPadraoIdReceita'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.value = '';
        });
        var campoDia = document.getElementById('receitaDia');
        if (campoDia) campoDia.value = 1;
    }

    function setModoEdicao(ativo, receitaId) {
        var secaoVincular = document.getElementById('secaoVincularReceita');
        var secaoHistorico = document.getElementById('secaoHistoricoReceita');
        var btnExcluir = document.getElementById('receitaBtnExcluir');

        // A secção de vínculo é SEMPRE visível (criação e edição),
        // pois o utilizador pode querer definir um padrão desde o início.
        if (secaoVincular)  secaoVincular.classList.remove('hidden');
        if (secaoHistorico) secaoHistorico.classList.toggle('hidden', !ativo);
        if (btnExcluir)     btnExcluir.classList.toggle('hidden', !ativo);

        if (ativo && receitaId) {
            var formExcluir = document.getElementById('formExcluirReceita');
            if (formExcluir) formExcluir.action = URL_EXCLUIR.replace('{id}', receitaId);
        }
        resetarBtnVinculo();
    }

    function resetarBtnVinculo() {
        var btn = document.getElementById('btnVincularPadraoReceita');
        if (!btn) return;
        btn.innerHTML = '<i class="bi bi-search"></i> Vincular Padrão de Entrada';
        btn.className = [
            'w-full bg-[#151e32] border border-slate-700 border-dashed',
            'hover:border-emerald-500 text-emerald-500 text-xs font-bold uppercase',
            'tracking-wider py-3 rounded-xl transition-colors flex items-center justify-center gap-2',
        ].join(' ');
    }

    /**
     * Renderiza o histórico de transações vinculadas dentro de containerHistorico.
     * Usa data-action="desvincular-receita" em vez de onclick inline.
     * Event Delegation é registrada UMA VEZ no container (flag _delegationAttached).
     */
    function renderizarHistorico(containerHistorico, historico, receitaId) {
        if (!historico || historico.length === 0) {
            containerHistorico.innerHTML =
                '<p class="text-slate-500 text-xs text-center py-6">Nenhum lançamento vinculado ainda.</p>';
            return;
        }

        containerHistorico.innerHTML = historico.map(function (t) {
            var statusColor = t.pago ? 'text-emerald-400' : 'text-amber-400';
            var icon        = t.pago ? 'bi-check2-all'    : 'bi-clock';
            return (
                '<div class="flex justify-between items-center border-b border-slate-700/50 last:border-0 p-3 hover:bg-slate-800/30 transition-colors group/item">' +
                    '<div class="flex flex-col truncate pr-3">' +
                        '<span class="text-slate-200 text-xs font-bold truncate">' + t.descricao + '</span>' +
                        '<span class="text-slate-500 text-[10px]">' + t.data + '</span>' +
                    '</div>' +
                    '<div class="flex items-center gap-3">' +
                        '<span class="font-bold ' + statusColor + ' text-xs flex items-center gap-1.5 shrink-0 whitespace-nowrap">' +
                            'R$ ' + t.valor + ' <i class="bi ' + icon + '"></i>' +
                        '</span>' +
                        '<button type="button"' +
                            ' data-action="desvincular-receita"' +
                            ' data-transacao-id="' + t.id + '"' +
                            ' data-receita-id="' + receitaId + '"' +
                            ' class="text-slate-500 hover:text-red-400 transition-colors opacity-0 group-hover/item:opacity-100"' +
                            ' title="Desvincular">' +
                            '<i class="bi bi-x-circle-fill pointer-events-none"></i>' +
                        '</button>' +
                    '</div>' +
                '</div>'
            );
        }).join('');

        // Event Delegation para botões de desvincular — registrada apenas uma vez
        if (!containerHistorico._delegationAttached) {
            containerHistorico._delegationAttached = true;
            containerHistorico.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-action="desvincular-receita"]');
                if (!btn) return;
                var transacaoId = parseInt(btn.getAttribute('data-transacao-id'), 10);
                var recId       = parseInt(btn.getAttribute('data-receita-id'),   10);
                window.desvincularTransacaoReceita(transacaoId, recId);
            });
        }
    }

    // ── API Pública ──────────────────────────────────────────────

    /**
     * Abre o modal em modo CRIAÇÃO (nova receita).
     */
    window.abrirModalNovaReceitaPlanejada = function (macroId, macroNome) {
        cacheOpcoesCategoriaReceita();

        receitaIdAtual = null;

        var form = document.getElementById('formReceitaPlanejada');
        if (form) form.action = URL_CADASTRAR;

        var titulo = document.getElementById('modalReceitaTitulo');
        if (titulo) titulo.textContent = 'Nova Fonte de Receita';

        var btnSubmit = document.getElementById('receitaBtnSubmit');
        if (btnSubmit) btnSubmit.textContent = 'CADASTRAR RECEITA';

        var macroInput = document.getElementById('macroIdNovaReceita');
        if (macroInput) macroInput.value = macroId || '';
        
        window.currentMacroNome = macroNome || '';

        var subtitulo = document.getElementById('modalNovaReceitaSubtitulo');
        if (subtitulo) {
            subtitulo.textContent = macroNome
                ? macroNome + ' — escolha a subcategoria'
                : 'Planeje uma entrada recorrente';
        }

        limparCamposReceita();
        setModoEdicao(false, null);
        filtrarCategoriasReceitaPorMacro(macroId, null);
        
        var toggleNova = document.getElementById('tem_vencimento_receita');
        if (toggleNova) {
            toggleNova.checked = false;
            toggleNova.dispatchEvent(new Event('change'));
        }

        document.getElementById('modalNovaReceitaPlanejada').classList.remove('hidden');
    };

    /**
     * Abre o modal em modo EDIÇÃO via AJAX, buscando todos os dados pelo id.
     * Análogo a abrirModalDespesa(id) em despesa_fixa_modais.js.
     *
     * @param {number} id - PK da ReceitaPlanejada
     */
    window.abrirModalReceita = function (id) {
        cacheOpcoesCategoriaReceita();

        receitaIdAtual = id;

        var form = document.getElementById('formReceitaPlanejada');
        if (form) form.action = URL_EDITAR.replace('{id}', id);

        var titulo = document.getElementById('modalReceitaTitulo');
        if (titulo) titulo.textContent = 'Gerenciar Receita';

        var btnSubmit = document.getElementById('receitaBtnSubmit');
        if (btnSubmit) btnSubmit.textContent = 'SALVAR ALTERAÇÕES';

        var subtitulo = document.getElementById('modalNovaReceitaSubtitulo');
        if (subtitulo) subtitulo.textContent = 'Edite os detalhes ou vincule um padrão de importação';

        setModoEdicao(true, id);

        // Spinner no histórico enquanto aguarda o fetch
        var containerHistorico = document.getElementById('historicoContainerReceita');
        if (containerHistorico) {
            containerHistorico.innerHTML =
                '<div class="text-center text-slate-500 py-6 text-sm">' +
                '<i class="bi bi-arrow-repeat animate-spin text-xl text-emerald-500 block mb-2"></i> Buscando...</div>';
        }

        document.getElementById('modalNovaReceitaPlanejada').classList.remove('hidden');

        // Fetch AJAX — popula campos com dados reais do backend
        fetch(URL_DETALHES.replace('{id}', id))
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var el;
                el = document.getElementById('receitaNome');        if (el) el.value = data.nome || '';
                el = document.getElementById('receitaValor');       if (el) el.value = data.valor_previsto || '';
                el = document.getElementById('receitaDia');         if (el) el.value = data.dia_recebimento || 1;
                el = document.getElementById('receitaDataInicio');  if (el) el.value = data.data_inicio || '';
                el = document.getElementById('receitaDataFim');     if (el) el.value = data.data_fim || '';
                el = document.getElementById('macroIdNovaReceita'); if (el) el.value = data.macro_categoria_id || '';

                var toggleReceita = document.getElementById('tem_vencimento_receita');
                if (toggleReceita) {
                    toggleReceita.checked = data.tem_vencimento;
                    toggleReceita.dispatchEvent(new Event('change'));
                }

                filtrarCategoriasReceitaPorMacro(data.macro_categoria_id, data.categoria_id);

                if (containerHistorico) {
                    renderizarHistorico(containerHistorico, data.historico, id);
                }
            })
            .catch(function (e) {
                console.error('[Receita Modal] Erro ao buscar detalhes:', e);
                if (containerHistorico) {
                    containerHistorico.innerHTML =
                        '<p class="text-red-400 text-xs text-center py-6">Erro ao carregar dados. Tente novamente.</p>';
                }
            });
    };

    window.fecharModalNovaReceitaPlanejada = function () {
        document.getElementById('modalNovaReceitaPlanejada').classList.add('hidden');
        receitaIdAtual = null;
    };

    window.excluirReceitaPlanejada = function () {
        if (!confirm('Atenção: Deseja excluir esta fonte de receita? (Os lançamentos passados não serão apagados)')) return;
        var form = document.getElementById('formExcluirReceita');
        if (form) form.submit();
    };

    // ── Busca de transações de receita ────────────────────────────

    window.abrirBuscaTransacaoReceita = function () {
        document.getElementById('modalBuscaTransacaoReceita').classList.remove('hidden');
        buscarTransacoesReceitaAPI('');
    };

    window.fecharBuscaTransacaoReceita = function () {
        document.getElementById('modalBuscaTransacaoReceita').classList.add('hidden');
    };

    window.confirmarVinculoReceita = function (id, descricao) {
        if (!confirm('Deseja usar "' + descricao + '" como padrão?\nSempre que o sistema importar algo parecido, será classificado automaticamente nesta Receita.')) {
            return;
        }
        var input = document.getElementById('transacaoPadraoIdReceita');
        if (input) input.value = id;

        var btn = document.getElementById('btnVincularPadraoReceita');
        if (btn) {
            btn.innerHTML = '<i class="bi bi-check2-all text-lg"></i> Vinculado: ' + descricao.substring(0, 18) + '...';
            btn.className = [
                'w-full bg-emerald-500/10 border border-emerald-500/30 border-solid',
                'text-emerald-400 text-xs font-bold uppercase tracking-wider py-3',
                'rounded-xl transition-colors flex items-center justify-center gap-2',
            ].join(' ');
        }
        window.fecharBuscaTransacaoReceita();
    };

    window.desvincularTransacaoReceita = async function (transacaoId, receitaId) {
        if (!confirm('Deseja remover o vínculo desta transação com esta Receita? (A transação não será apagada do sistema, apenas desvinculada).')) return;
        try {
            var response = await fetch(URL_DESVINCULAR.replace('{id}', transacaoId), {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() },
            });
            if (response.ok) {
                // Recarrega o modal inteiro para refletir a mudança no histórico
                window.abrirModalReceita(receitaId);
            }
        } catch (e) {
            alert('Erro ao desvincular. Tente novamente.');
        }
    };

    // ── Busca interna (privada) ───────────────────────────────────

    async function buscarTransacoesReceitaAPI(termo) {
        try {
            var response = await fetch(URL_BUSCA + encodeURIComponent(termo));
            var data = await response.json();
            var lista = document.getElementById('listaTransacoesBuscaReceita');
            if (!lista) return;

            lista.innerHTML = '';

            if (!data.transacoes || data.transacoes.length === 0) {
                lista.innerHTML =
                    '<p class="text-xs text-slate-500 text-center py-6 font-bold uppercase tracking-wide">Nenhuma entrada encontrada</p>';
                return;
            }

            // Constrói itens via DOM (sem innerHTML + onclick = sem problema de escopo)
            data.transacoes.forEach(function (t) {
                var div = document.createElement('div');
                div.className = 'p-3 bg-slate-800/50 hover:bg-slate-700 rounded-xl cursor-pointer border border-slate-700/50 flex justify-between items-center transition-colors group';
                div.innerHTML =
                    '<div class="overflow-hidden pr-2">' +
                        '<p class="text-sm text-slate-200 font-bold truncate group-hover:text-emerald-400 transition-colors">' + t.descricao + '</p>' +
                        '<p class="text-[10px] text-slate-500 mt-0.5"><i class="bi bi-calendar3"></i> ' + t.data + '</p>' +
                    '</div>' +
                    '<span class="text-xs font-black text-emerald-400 whitespace-nowrap bg-[#0f172a] px-2 py-1 rounded-md">+ R$ ' + Number(t.valor).toFixed(2) + '</span>';
                // Listener direto no elemento (não inline) — captura t por closure corretamente
                div.addEventListener('click', function () {
                    window.confirmarVinculoReceita(t.id, t.descricao);
                });
                lista.appendChild(div);
            });
        } catch (err) {
            console.error('[Receita Modal] Erro ao buscar transações:', err);
        }
    }    window.recarregarCategoriasReceita = function (novasCategorias, macroId) {
        cacheOpcoesCategoriaReceita();
        if (!todasOpcoesCategoriaReceita) return;

        var select = document.getElementById('categoriaNovaReceita');
        var currentValue = select ? select.value : '';

        todasOpcoesCategoriaReceita = todasOpcoesCategoriaReceita.filter(function (opt) {
            return opt.macroId !== String(macroId);
        });

        var macroNome = window.currentMacroNome;
        if (!macroNome && select) {
            var firstOpt = todasOpcoesCategoriaReceita.find(function (opt) { return opt.macroId === String(macroId); });
            if (firstOpt) {
                var parts = firstOpt.text.split('>');
                if (parts.length > 1) macroNome = parts[0].trim();
            }
        }

        novasCategorias.forEach(function (cat) {
            todasOpcoesCategoriaReceita.push({
                value: String(cat.id),
                text: macroNome ? (macroNome + ' > ' + cat.nome) : cat.nome,
                macroId: String(macroId)
            });
        });

        // Use current selection if valid, else let it filter
        filtrarCategoriasReceitaPorMacro(macroId, currentValue);

        if (select) {
            var exists = novasCategorias.some(function (cat) { return String(cat.id) === String(currentValue); });
            if (exists) {
                select.value = currentValue;
            } else {
                select.value = '';
            }
        }
    };

    // ── Inicialização ─────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        cacheOpcoesCategoriaReceita();

        var inputBusca = document.getElementById('inputBuscaTransacaoReceita');
        if (inputBusca) {
            inputBusca.addEventListener('input', function (e) {
                buscarTransacoesReceitaAPI(e.target.value);
            });
        }
        
        var toggleReceita = document.getElementById('tem_vencimento_receita');
        var wrapperReceita = document.getElementById('wrapper-datas-receita');
        var diaReceita = document.getElementById('receitaDia');
        var inicioReceita = document.getElementById('receitaDataInicio');
        
        if (toggleReceita && wrapperReceita) {
            toggleReceita.addEventListener('change', function() {
                if (this.checked) {
                    wrapperReceita.classList.remove('hidden');
                    if(diaReceita) diaReceita.required = true;
                    if(inicioReceita) inicioReceita.required = true;
                } else {
                    wrapperReceita.classList.add('hidden');
                    if(diaReceita) {
                        diaReceita.required = false;
                        diaReceita.value = '';
                    }
                    if(inicioReceita) {
                        inicioReceita.required = false;
                        inicioReceita.value = '';
                    }
                }
            });
        }
    });

})();
