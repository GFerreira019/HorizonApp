/**
 * Modal de provisionamentos por macro (Planejamento — Distribuição do Orçamento).
 *
 * ARQUITETURA: mantém IIFE para estado privado (macroIdAtual, macroTipoAtual),
 * mas expõe TODAS as funções que o DOM dinâmico ou outros módulos precisam via window.
 * Toda interação com elementos gerados dinamicamente usa Event Delegation,
 * eliminando a dependência de onclick inline e erros de escopo.
 */
(function () {
    'use strict';

    // ── Estado privado ───────────────────────────────────────────
    var macroIdAtual   = null;
    var macroTipoAtual = null;

    // ── Utilitários expostos no window (usados pelo DOM dinâmico) ─

    window.formatarMoeda = function (valor) {
        return 'R$ ' + Number(valor || 0).toLocaleString('pt-BR', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    };

    window.escaparHtml = function (texto) {
        var div = document.createElement('div');
        div.textContent = texto;
        return div.innerHTML;
    };

    window.iconeCorPorTipo = function (tipo) {
        if (tipo === 'receita')   return { icone: 'text-emerald-400', valor: 'text-emerald-400' };
        if (tipo === 'reservado') return { icone: 'text-amber-400',   valor: 'text-amber-400'   };
        return                           { icone: 'text-red-400',     valor: 'text-red-400'     };
    };

    /** Retorna classes Tailwind para o botão "Cadastrar" conforme o tipo. */
    window.classesBtnCadastrarPorTipo = function (tipo) {
        if (tipo === 'receita') {
            return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:border-emerald-400/60 hover:text-emerald-300';
        }
        if (tipo === 'reservado') {
            return 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:border-amber-400/60 hover:text-amber-300';
        }
        return 'bg-red-500/10 text-red-400 border-red-500/30 hover:border-red-400/60 hover:text-red-300';
    };

    /** Fecha todos os dropdowns de item abertos, exceto o passado como argumento. */
    window.fecharTodosDropdowns = function (exceto) {
        document.querySelectorAll('.item-dropdown-menu').forEach(function (menu) {
            if (menu !== exceto) menu.classList.add('hidden');
        });
    };

    // ── Fecha dropdowns ao clicar fora de qualquer wrapper ────────
    document.addEventListener('click', function (e) {
        if (!e.target.closest('.item-opcoes-wrapper')) {
            window.fecharTodosDropdowns(null);
        }
    });

    // ── Helpers privados ─────────────────────────────────────────

    function obterDadosMacro(macroId) {
        var mapa = window.HORIZON_PROVISIONAMENTOS_POR_MACRO || {};
        return mapa[String(macroId)] || null;
    }

    // ── Renderização da lista (sem nenhum onclick inline) ─────────

    /**
     * Constrói o HTML da lista de itens do modal macro.
     * Toda interação é gerida por Event Delegation via data-action.
     */
    window.renderizarListaMacro = function (itens, tipo, macroId, macroNome) {
        var lista = document.getElementById('modalMacroLista');
        if (!lista) return;

        var cores = window.iconeCorPorTipo(tipo);

        if (!itens || itens.length === 0) {
            var labelVazio = tipo === 'receita' ? 'Nenhuma fonte de receita vinculada'
                           : tipo === 'reservado' ? 'Nenhuma reserva vinculada'
                           : 'Nenhuma conta vinculada';
            lista.innerHTML =
                '<div class="flex flex-col items-center justify-center py-10 text-center">' +
                '<i class="bi bi-inbox text-3xl text-slate-600 mb-3"></i>' +
                '<p class="text-xs text-slate-500 font-bold uppercase tracking-wider">' + labelVazio + '</p>' +
                '<p class="text-[10px] text-slate-600 mt-1">Use o botão abaixo para cadastrar</p>' +
                '</div>';
            return;
        }

        lista.innerHTML = itens.map(function (item) {
            var dropdownId = 'dropdown_item_' + tipo + '_' + item.id;
            // Badge de "Envelope" para registros sem vencimento (tem_vencimento=false)
            var metaHtml = item.tem_vencimento === false
                ? '<span class="inline-flex items-center gap-1 text-[9px] font-bold text-slate-400 bg-slate-800 border border-slate-700 px-1.5 py-0.5 rounded-md uppercase tracking-wider mt-0.5">' +
                  '<i class="bi bi-inbox pointer-events-none"></i> Envelope</span>'
                : '<p class="text-[10px] text-slate-500 truncate">' + window.escaparHtml(item.categoria_nome || '') + '</p>';
            return (
                '<div class="flex items-center gap-2 p-3 rounded-xl bg-[#0f172a] border border-slate-800 hover:border-slate-600 transition-colors group">' +
                    '<div class="flex-1 min-w-0">' +
                        '<p class="text-sm font-bold text-slate-200 truncate">' + window.escaparHtml(item.nome) + '</p>' +
                        metaHtml +
                    '</div>' +
                    '<span class="text-sm font-bold ' + cores.valor + ' shrink-0 whitespace-nowrap">' +
                        window.formatarMoeda(item.valor) +
                    '</span>' +
                    // Botão de opções — sem onclick; Event Delegation captura via data-action
                    '<div class="item-opcoes-wrapper relative shrink-0">' +
                        '<button type="button"' +
                            ' data-action="toggle-dropdown"' +
                            ' data-dropdown-id="' + dropdownId + '"' +
                            ' class="h-8 w-8 rounded-lg text-slate-500 hover:text-cyan-400 hover:bg-slate-700/50 flex items-center justify-center transition-colors"' +
                            ' title="Opções">' +
                            '<i class="bi bi-three-dots-vertical text-sm pointer-events-none"></i>' +
                        '</button>' +
                        '<div id="' + dropdownId + '" class="item-dropdown-menu hidden absolute right-0 top-9 z-[80] min-w-[140px] bg-[#1e2d45] border border-slate-700 rounded-xl shadow-2xl py-1 overflow-hidden">' +
                            '<button type="button"' +
                                ' data-action="editar"' +
                                ' data-tipo="' + tipo + '"' +
                                ' data-id="' + item.id + '"' +
                                ' class="w-full text-left px-4 py-2.5 text-xs font-bold text-slate-300 hover:text-white hover:bg-slate-700/60 flex items-center gap-2.5 transition-colors">' +
                                '<i class="bi bi-pencil-square text-cyan-400 pointer-events-none"></i> Editar' +
                            '</button>' +
                            '<div class="border-t border-slate-800/60 my-0.5"></div>' +
                            '<button type="button"' +
                                ' data-action="excluir"' +
                                ' data-tipo="' + tipo + '"' +
                                ' data-id="' + item.id + '"' +
                                ' class="w-full text-left px-4 py-2.5 text-xs font-bold text-red-400 hover:text-red-300 hover:bg-red-500/10 flex items-center gap-2.5 transition-colors">' +
                                '<i class="bi bi-trash3 pointer-events-none"></i> Excluir' +
                            '</button>' +
                        '</div>' +
                    '</div>' +
                '</div>'
            );
        }).join('');

        // Event Delegation — captura cliques em qualquer botão data-action dentro da lista
        // Registrado após cada render para garantir que aponta para o conteúdo atual.
        // Usamos uma flag no elemento para evitar múltiplos listeners acumulados.
        if (!lista._horizonDelegationAttached) {
            lista._horizonDelegationAttached = true;
            lista.addEventListener('click', function (e) {
                // Toggle dropdown
                var btnToggle = e.target.closest('[data-action="toggle-dropdown"]');
                if (btnToggle) {
                    e.stopPropagation();
                    window.toggleDropdownItem(btnToggle.getAttribute('data-dropdown-id'));
                    return;
                }

                // Editar item
                var btnEditar = e.target.closest('[data-action="editar"]');
                if (btnEditar) {
                    e.stopPropagation();
                    window.editarItem(
                        btnEditar.getAttribute('data-tipo'),
                        parseInt(btnEditar.getAttribute('data-id'), 10)
                    );
                    return;
                }

                // Excluir item
                var btnExcluir = e.target.closest('[data-action="excluir"]');
                if (btnExcluir) {
                    e.stopPropagation();
                    window.removerProvisionamento(
                        btnExcluir.getAttribute('data-tipo'),
                        parseInt(btnExcluir.getAttribute('data-id'), 10)
                    );
                    return;
                }
            });
        }
    };

    // ── Ações do dropdown ────────────────────────────────────────

    window.toggleDropdownItem = function (dropdownId) {
        var menu = document.getElementById(dropdownId);
        if (!menu) return;
        var estaAberto = !menu.classList.contains('hidden');
        window.fecharTodosDropdowns(null);
        if (!estaAberto) menu.classList.remove('hidden');
    };

    /**
     * Despacha para o modal correto conforme o tipo do item.
     * @param {string} tipo  - 'receita' | 'despesa' | 'reservado'
     * @param {number} id    - PK do item no banco de dados
     */
    window.editarItem = function (tipo, id) {
        window.fecharTodosDropdowns(null);
        window.fecharModalMacroProvisionamento();

        setTimeout(function () {
            if (tipo === 'receita') {
                if (typeof window.abrirModalReceita === 'function') {
                    window.abrirModalReceita(id);
                } else {
                    console.warn('abrirModalReceita não está definida. Verifique se receita_planejada_modal.js foi carregado.');
                }
            } else {
                // Despesas e Reservados usam o modal existente de DespesaFixa
                if (typeof window.abrirModalDespesa === 'function') {
                    window.abrirModalDespesa(id);
                } else {
                    console.warn('abrirModalDespesa não está definida. Verifique se despesa_fixa_modais.js foi carregado.');
                }
            }
        }, 220);
    };

    window.removerProvisionamento = function (tipo, id) {
        window.fecharTodosDropdowns(null);
        var labels = { receita: 'esta fonte de receita', despesa: 'esta conta fixa', reservado: 'esta conta fixa' };
        var label = labels[tipo] || 'este item';
        if (!confirm('Deseja remover ' + label + '?')) return;

        var form = document.getElementById('formExcluirProvisionamento');
        if (!form) return;
        form.action = tipo === 'receita'
            ? '/receitas-planejadas/' + id + '/excluir/'
            : '/fixos/' + id + '/excluir/';
        form.submit();
    };

    // ── Abertura / Fechamento do modal macro ─────────────────────

    window.abrirModalMacroProvisionamento = function (macroId) {
        var dados = obterDadosMacro(macroId);
        if (!dados) return;

        macroIdAtual   = macroId;
        macroTipoAtual = dados.tipo;

        var modal    = document.getElementById('modalMacroProvisionamento');
        var content  = document.getElementById('modalMacroProvisionamentoContent');
        var titulo   = document.getElementById('modalMacroTitulo');
        var soma     = document.getElementById('modalMacroSoma');
        var icone    = document.getElementById('modalMacroIcone');
        var btnTexto = document.getElementById('modalMacroBtnCadastrarTexto');
        var btnCadastrar = document.getElementById('modalMacroBtnCadastrar');
        var subtitulo = document.getElementById('modalMacroSubtitulo');

        if (titulo)   titulo.textContent = dados.nome;
        if (soma)     soma.textContent   = window.formatarMoeda(dados.soma);
        if (icone && dados.icone) {
            icone.className = 'bi ' + dados.icone + ' ' + window.iconeCorPorTipo(dados.tipo).icone;
        }

        // Textos dinâmicos por tipo
        if (dados.tipo === 'receita') {
            if (subtitulo) subtitulo.textContent = 'Fontes de receita';
            if (btnTexto)  btnTexto.textContent  = 'Cadastrar nova fonte de receita';
        } else if (dados.tipo === 'reservado') {
            if (subtitulo) subtitulo.textContent = 'Aportes vinculados';
            if (btnTexto)  btnTexto.textContent  = 'Cadastrar nova reserva';
        } else {
            if (subtitulo) subtitulo.textContent = 'Contas fixas vinculadas';
            if (btnTexto)  btnTexto.textContent  = 'Cadastrar nova conta fixa';
        }

        // Cores dinâmicas no botão "Cadastrar"
        if (btnCadastrar) {
            // Reseta para classes base e aplica as do tipo atual
            btnCadastrar.className = 'w-full py-3 rounded-xl text-xs font-bold uppercase tracking-wider border active:scale-[0.98] transition-all flex items-center justify-center gap-2 '
                + window.classesBtnCadastrarPorTipo(dados.tipo);
        }

        window.renderizarListaMacro(dados.itens || [], dados.tipo, macroId, dados.nome);

        modal.classList.remove('hidden');
        setTimeout(function () {
            content.classList.remove('scale-95', 'opacity-0');
            content.classList.add('scale-100', 'opacity-100');
        }, 10);
    };

    window.fecharModalMacroProvisionamento = function () {
        var modal   = document.getElementById('modalMacroProvisionamento');
        var content = document.getElementById('modalMacroProvisionamentoContent');
        if (!modal || !content) return;

        window.fecharTodosDropdowns(null);
        content.classList.remove('scale-100', 'opacity-100');
        content.classList.add('scale-95', 'opacity-0');
        setTimeout(function () {
            modal.classList.add('hidden');
            macroIdAtual   = null;
            macroTipoAtual = null;
        }, 200);
    };

    // ── Botão "Cadastrar novo" no rodapé do modal macro ──────────

    document.addEventListener('DOMContentLoaded', function () {
        var btnCadastrar = document.getElementById('modalMacroBtnCadastrar');
        if (!btnCadastrar) return;

        btnCadastrar.addEventListener('click', function () {
            if (!macroIdAtual) return;
            var dados = obterDadosMacro(macroIdAtual);
            var nome  = dados ? dados.nome : '';
            var tipo  = macroTipoAtual;
            var id    = macroIdAtual;

            window.fecharModalMacroProvisionamento();

            setTimeout(function () {
                if (tipo === 'receita') {
                    if (typeof window.abrirModalNovaReceitaPlanejada === 'function') {
                        window.abrirModalNovaReceitaPlanejada(id, nome);
                    }
                } else if (typeof window.abrirModalNovaDespesaFixa === 'function') {
                    window.abrirModalNovaDespesaFixa(id, nome);
                }
            }, 220);
        });
    });

    // ── Quick Add: Lançamento Avulso ─────────────────────────────

    /** Exibe ou esconde o banner de erro inline do Quick Add. */
    function _mostrarErroQuickAdd(mensagem) {
        var erroBox  = document.getElementById('quickAddErro');
        var erroText = document.getElementById('quickAddErroTexto');
        if (!erroBox || !erroText) return;
        if (mensagem) {
            erroText.textContent = mensagem;
            erroBox.classList.remove('hidden');
        } else {
            erroBox.classList.add('hidden');
            erroText.textContent = '';
        }
    }

    /**
     * Lê os campos do Quick Add, faz um POST AJAX para /api/quick-add-provisionamento/
     * e atualiza o modal inline com o novo item + soma recalculada.
     * Um reload silencioso acontece ao fechar o modal para sincronizar o card principal.
     */
    window.adicionarValorAvulso = function () {
        var nomeInput  = document.getElementById('quickAddNome');
        var valorInput = document.getElementById('quickAddValor');
        var btn        = document.getElementById('quickAddBtn');
        var btnIcone   = document.getElementById('quickAddBtnIcone');

        if (!nomeInput || !valorInput) return;

        var nome  = nomeInput.value.trim();
        var valor = parseFloat(valorInput.value);

        // Validação client-side rápida
        _mostrarErroQuickAdd(null);
        if (!nome) {
            _mostrarErroQuickAdd('Informe um nome para o lançamento.');
            nomeInput.focus();
            return;
        }
        if (!valor || valor <= 0) {
            _mostrarErroQuickAdd('Informe um valor positivo.');
            valorInput.focus();
            return;
        }
        if (!macroIdAtual) {
            _mostrarErroQuickAdd('Nenhuma macro selecionada.');
            return;
        }

        // Estado de loading no botão
        if (btn)      btn.disabled = true;
        if (btnIcone) btnIcone.className = 'bi bi-arrow-repeat animate-spin text-base pointer-events-none';

        var url       = window.HORIZON_QUICK_ADD_URL || '/api/quick-add-provisionamento/';
        var csrfToken = window.HORIZON_CSRF_TOKEN || '';

        var hojeStr = new Date().toISOString().split('T')[0];

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
            },
            body: new URLSearchParams({
                nome:           nome,
                valor:          valor,
                macro_id:       macroIdAtual,
                valor_previsto: valor,
                dia_vencimento: 1,
                dia_recebimento: 1,
                data_inicio:    hojeStr,
                categoria:      ''
            }),
        })
        .then(function (response) {
            return response.json().then(function (data) {
                return { ok: response.ok, data: data };
            });
        })
        .then(function (result) {
            if (!result.ok || result.data.status !== 'ok') {
                _mostrarErroQuickAdd(result.data.mensagem || 'Erro desconhecido. Tente novamente.');
                return;
            }

            var data = result.data;

            // Atualiza o total exibido no cabeçalho do modal
            var somaEl = document.getElementById('modalMacroSoma');
            if (somaEl) somaEl.textContent = window.formatarMoeda(data.nova_soma);

            // Atualiza também o mapa interno para que a lista renderize o novo item
            var mapa = window.HORIZON_PROVISIONAMENTOS_POR_MACRO || {};
            var macroData = mapa[String(macroIdAtual)];
            if (macroData) {
                macroData.itens.push(data.item);
                macroData.soma = data.nova_soma;
                window.renderizarListaMacro(macroData.itens, macroData.tipo, macroIdAtual, macroData.nome);
            }

            // Limpa os campos do Quick Add
            nomeInput.value  = '';
            valorInput.value = '';
            _mostrarErroQuickAdd(null);

            // Sinaliza que a página precisa de reload ao fechar
            window._horizonQuickAddPendingReload = true;
        })
        .catch(function (err) {
            console.error('[QuickAdd] Erro de rede:', err);
            _mostrarErroQuickAdd('Falha na conexão. Verifique sua internet e tente novamente.');
        })
        .finally(function () {
            // Restaura o botão
            if (btn)      btn.disabled = false;
            if (btnIcone) btnIcone.className = 'bi bi-plus-lg text-base pointer-events-none';
        });
    };

    // ── Patch no fechar modal: reload se Quick Add foi usado ─────

    var _fecharOriginal = window.fecharModalMacroProvisionamento;
    window.fecharModalMacroProvisionamento = function () {
        _fecharOriginal();
        if (window._horizonQuickAddPendingReload) {
            window._horizonQuickAddPendingReload = false;
            // Aguarda a animação de fechamento (200ms) antes de recarregar
            setTimeout(function () { window.location.reload(); }, 250);
        }
    };

})();
