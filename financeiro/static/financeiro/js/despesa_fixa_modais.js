/**
 * Modais compartilhados de despesa fixa (Planejamento e Custos Fixos).
 */
(function () {
    'use strict';

    let contextoBuscaAtual = 'nova';
    let todasOpcoesCategoria = null;

    function getCsrfToken() {
        const input = document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function initSelect2Categoria() {
        if (typeof jQuery === 'undefined' || !jQuery.fn.select2) return;
        const $el = jQuery('#categoriaNovaDespesa');
        if (!$el.length) return;
        if ($el.hasClass('select2-hidden-accessible')) {
            $el.select2('destroy');
        }
        $el.select2({
            placeholder: 'Pesquise a categoria...',
            dropdownParent: jQuery('#modalNovaDespesa'),
            width: '100%',
        });
    }

    function cacheOpcoesCategoria() {
        const select = document.getElementById('categoriaNovaDespesa');
        if (!select || todasOpcoesCategoria) return;
        todasOpcoesCategoria = Array.from(select.querySelectorAll('option')).map(function (opt) {
            return {
                value: opt.value,
                text: opt.textContent,
                macroId: opt.getAttribute('data-macro-id'),
                disabled: opt.disabled,
                selected: opt.selected,
            };
        });
    }

    function filtrarCategoriasPorMacro(macroId) {
        const select = document.getElementById('categoriaNovaDespesa');
        if (!select || !todasOpcoesCategoria) return;

        const macroKey = macroId ? String(macroId) : null;
        select.innerHTML = '';

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.disabled = true;
        placeholder.selected = true;
        placeholder.textContent = 'Selecione uma categoria...';
        select.appendChild(placeholder);

        const filtradas = todasOpcoesCategoria.filter(function (opt) {
            if (!opt.value) return false;
            if (!macroKey) return true;
            return opt.macroId === macroKey;
        });

        filtradas.forEach(function (opt) {
            const option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.text;
            option.setAttribute('data-macro-id', opt.macroId || '');
            select.appendChild(option);
        });

        if (filtradas.length === 1) {
            select.value = filtradas[0].value;
        }

        if (typeof jQuery !== 'undefined' && jQuery.fn.select2) {
            jQuery(select).trigger('change');
        }
    }

    window.abrirModalNovaDespesaFixa = function (macroId, macroNome) {
        cacheOpcoesCategoria();

        const macroInput = document.getElementById('macroIdNovaDespesa');
        if (macroInput) macroInput.value = macroId || '';
        
        window.currentMacroNome = macroNome || '';

        const subtitulo = document.getElementById('modalNovaDespesaSubtitulo');
        if (subtitulo) {
            subtitulo.textContent = macroNome
                ? macroNome + ' — escolha a subcategoria'
                : 'Planeje um gasto sem gerar transação real';
        }

        filtrarCategoriasPorMacro(macroId);
        
        const toggleNova = document.getElementById('tem_vencimento_nova');
        if (toggleNova) {
            toggleNova.checked = false;
            toggleNova.dispatchEvent(new Event('change'));
        }
        
        document.getElementById('modalNovaDespesa').classList.remove('hidden');
    };

    window.abrirModalNovaDespesa = function () {
        abrirModalNovaDespesaFixa(null, null);
    };

    window.fecharModalNovaDespesa = function () {
        document.getElementById('modalNovaDespesa').classList.add('hidden');
    };

    window.abrirModalDespesa = function (id) {
        document.getElementById('modalDespesa').classList.remove('hidden');
        document.getElementById('formEditDespesa').action = '/fixos/' + id + '/editar/';
        document.getElementById('formExcluirDespesa').action = '/fixos/' + id + '/excluir/';

        const btnEdicao = document.getElementById('btnVincularPadraoEdicao');
        btnEdicao.innerHTML = '<i class="bi bi-search"></i> Vincular Novo Padrão';
        btnEdicao.className = 'w-full bg-[#151e32] border border-slate-700 border-dashed hover:border-cyan-500 text-cyan-500 text-xs font-bold uppercase tracking-wider py-3 rounded-xl transition-colors flex items-center justify-center gap-2';
        document.getElementById('transacao_padrao_id_edicao').value = '';

        const container = document.getElementById('historicoContainer');
        container.innerHTML = '<div class="text-center text-slate-500 py-6 text-sm"><i class="bi bi-arrow-repeat animate-spin text-xl text-cyan-500 block mb-2"></i> Buscando...</div>';

        fetch('/fixos/' + id + '/detalhes/')
            .then(function (response) { return response.json(); })
            .then(function (data) {
                document.getElementById('modalNome').value = data.nome;
                document.getElementById('modalValor').value = data.valor_previsto;
                document.getElementById('modalDia').value = data.dia_vencimento || '';
                document.getElementById('modalInicio').value = data.data_inicio || '';
                document.getElementById('modalFim').value = data.data_fim || '';
                
                const toggleEdicao = document.getElementById('tem_vencimento_edicao');
                if (toggleEdicao) {
                    toggleEdicao.checked = data.tem_vencimento;
                    toggleEdicao.dispatchEvent(new Event('change'));
                }

                container.innerHTML = '';
                if (data.historico.length === 0) {
                    container.innerHTML = '<p class="text-slate-500 text-xs text-center py-6">Nenhum lançamento vinculado ainda.</p>';
                } else {
                    data.historico.forEach(function (t) {
                        const statusColor = t.pago ? 'text-emerald-400' : 'text-amber-400';
                        const icon = t.pago ? 'bi-check2-all' : 'bi-clock';
                        container.innerHTML +=
                            '<div class="flex justify-between items-center border-b border-slate-700/50 last:border-0 p-3 hover:bg-slate-800/30 transition-colors group/item">' +
                            '<div class="flex flex-col truncate pr-3">' +
                            '<span class="text-slate-200 text-xs font-bold truncate">' + t.descricao + '</span>' +
                            '<span class="text-slate-500 text-[10px]">' + t.data + '</span>' +
                            '</div>' +
                            '<div class="flex items-center gap-3">' +
                            '<span class="font-bold ' + statusColor + ' text-xs flex items-center gap-1.5 shrink-0 whitespace-nowrap">' +
                            'R$ ' + t.valor + ' <i class="bi ' + icon + '"></i></span>' +
                            '<button type="button" onclick="desvincularTransacao(' + t.id + ', ' + id + ')" class="text-slate-500 hover:text-red-400 transition-colors opacity-0 group-hover/item:opacity-100" title="Desvincular Histórico">' +
                            '<i class="bi bi-x-circle-fill"></i></button></div></div>';
                    });
                }
            });
    };

    window.fecharModalDespesa = function () {
        document.getElementById('modalDespesa').classList.add('hidden');
    };

    window.desvincularTransacao = async function (transacaoId, despesaId) {
        if (!confirm('Deseja remover o vínculo desta transação com esta Conta Fixa? (A transação não será apagada do sistema, apenas desvinculada).')) {
            return;
        }
        try {
            const response = await fetch('/fixos/desvincular/' + transacaoId + '/', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() },
            });
            if (response.ok) {
                abrirModalDespesa(despesaId);
            }
        } catch (e) {
            alert('Erro ao desvincular.');
        }
    };

    window.abrirBuscaTransacao = function (contexto) {
        contextoBuscaAtual = contexto || 'nova';
        document.getElementById('modalBuscaTransacao').classList.remove('hidden');
        buscarTransacoesAPI('');
    };

    window.fecharBuscaTransacao = function () {
        document.getElementById('modalBuscaTransacao').classList.add('hidden');
    };

    window.confirmarVinculo = function (id, descricao) {
        if (!confirm('Deseja usar "' + descricao + '" como padrão? \nSempre que o sistema importar algo parecido, será classificado automaticamente neste Provisionamento.')) {
            return;
        }
        const inputId = contextoBuscaAtual === 'nova' ? 'transacao_padrao_id_nova_despesa' : 'transacao_padrao_id_edicao';
        const btnId = contextoBuscaAtual === 'nova' ? 'btnVincularPadrao' : 'btnVincularPadraoEdicao';
        document.getElementById(inputId).value = id;
        const btn = document.getElementById(btnId);
        btn.innerHTML = '<i class="bi bi-check2-all text-lg"></i> Vinculado: ' + descricao.substring(0, 18) + '...';
        btn.classList.remove('bg-slate-800/80', 'bg-[#151e32]', 'text-cyan-400', 'border-slate-700', 'border-dashed', 'hover:border-cyan-500');
        btn.classList.add('bg-emerald-500/10', 'text-emerald-400', 'border-emerald-500/30', 'border-solid');
        fecharBuscaTransacao();
    };

    window.excluirDespesa = function () {
        if (confirm('Atenção: Você tem certeza que deseja excluir este provisionamento? (Os lançamentos passados não serão apagados)')) {
            document.getElementById('formExcluirDespesa').submit();
        }
    };

    async function buscarTransacoesAPI(termo) {
        try {
            const response = await fetch('/api/buscar-transacoes/?q=' + encodeURIComponent(termo));
            const data = await response.json();
            const lista = document.getElementById('listaTransacoesBusca');
            lista.innerHTML = '';

            if (data.transacoes.length === 0) {
                lista.innerHTML = '<p class="text-xs text-slate-500 text-center py-6 font-bold uppercase tracking-wide">Nenhuma transação encontrada</p>';
                return;
            }

            data.transacoes.forEach(function (t) {
                const div = document.createElement('div');
                div.className = 'p-3 bg-slate-800/50 hover:bg-slate-700 rounded-xl cursor-pointer border border-slate-700/50 flex justify-between items-center transition-colors group';
                div.innerHTML =
                    '<div class="overflow-hidden pr-2">' +
                    '<p class="text-sm text-slate-200 font-bold truncate group-hover:text-cyan-400 transition-colors">' + t.descricao + '</p>' +
                    '<p class="text-[10px] text-slate-500 mt-0.5"><i class="bi bi-calendar3"></i> ' + t.data + '</p></div>' +
                    '<span class="text-xs font-black text-slate-300 whitespace-nowrap bg-[#0f172a] px-2 py-1 rounded-md">R$ ' + t.valor.toFixed(2) + '</span>';
                div.onclick = function () { confirmarVinculo(t.id, t.descricao); };
                lista.appendChild(div);
            });
        } catch (error) {
            console.error('Erro ao buscar transações:', error);
        }
    }    window.recarregarCategoriasDespesa = function (novasCategorias, macroId) {
        cacheOpcoesCategoria();
        if (!todasOpcoesCategoria) return;

        const select = document.getElementById('categoriaNovaDespesa');
        const currentValue = select ? select.value : '';

        todasOpcoesCategoria = todasOpcoesCategoria.filter(function (opt) {
            return opt.macroId !== String(macroId);
        });

        var macroNome = window.currentMacroNome;
        if (!macroNome && select) {
            var firstOpt = todasOpcoesCategoria.find(function (opt) { return opt.macroId === String(macroId); });
            if (firstOpt) {
                var parts = firstOpt.text.split('>');
                if (parts.length > 1) macroNome = parts[0].trim();
            }
        }

        novasCategorias.forEach(function (cat) {
            todasOpcoesCategoria.push({
                value: String(cat.id),
                text: macroNome ? (macroNome + ' > ' + cat.nome) : cat.nome,
                macroId: String(macroId)
            });
        });

        filtrarCategoriasPorMacro(macroId);

        if (select) {
            const exists = novasCategorias.some(function (cat) { return String(cat.id) === String(currentValue); });
            if (exists) {
                select.value = currentValue;
            } else {
                select.value = '';
            }
            if (typeof jQuery !== 'undefined' && jQuery.fn.select2) {
                jQuery(select).trigger('change');
            }
        }
    };

    document.addEventListener('DOMContentLoaded', function () {
        cacheOpcoesCategoria();
        initSelect2Categoria();

        const inputBusca = document.getElementById('inputBuscaTransacao');
        if (inputBusca) {
            inputBusca.addEventListener('input', function (e) {
                buscarTransacoesAPI(e.target.value);
            });
        }
        
        // Toggle Logic for tem_vencimento
        function initToggleLogic(checkboxId, wrapperId, inputDiaId, inputInicioId) {
            const checkbox = document.getElementById(checkboxId);
            const wrapper = document.getElementById(wrapperId);
            const inputDia = document.getElementById(inputDiaId);
            const inputInicio = document.getElementById(inputInicioId);
            
            if (checkbox && wrapper) {
                checkbox.addEventListener('change', function() {
                    if (this.checked) {
                        wrapper.classList.remove('hidden');
                        if(inputDia) inputDia.required = true;
                        if(inputInicio) inputInicio.required = true;
                    } else {
                        wrapper.classList.add('hidden');
                        if(inputDia) {
                            inputDia.required = false;
                            inputDia.value = '';
                        }
                        if(inputInicio) {
                            inputInicio.required = false;
                            inputInicio.value = '';
                        }
                    }
                });
            }
        }
        
        initToggleLogic('tem_vencimento_nova', 'wrapper-datas-nova', 'novaDespesaDia', 'novaDespesaInicio');
        initToggleLogic('tem_vencimento_edicao', 'wrapper-datas-edicao', 'modalDia', 'modalInicio');
    });
})();
