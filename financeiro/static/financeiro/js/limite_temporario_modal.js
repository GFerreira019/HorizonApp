/**
 * limite_temporario_modal.js
 * Modal de Limites Temporários de Gastos — HorizonAPP
 *
 * PADRÃO ADOTADO: IIFE com estado privado, expondo apenas as funções
 * necessárias no window — idêntico ao planejamento_macro_modal.js.
 * Toda interação com o backend usa fetch API (sem reload de página).
 *
 * INTEGRAÇÃO FUTURA:
 * - Open Finance: quando a API bancária sincronizar, o backend atualizará
 *   `valor_consumido` no banco. As barras de progresso nos cards serão
 *   recarregadas ao abrir a página (SSR via Django) ou via polling futuro.
 * - Telegram: `notificacao_enviada` é gerenciado pelo backend — este JS
 *   não precisa conhecer esse campo; ele apenas cria/desativa limites.
 */
(function () {
    'use strict';

    // ── Estado privado ────────────────────────────────────────────
    var _modalAberto = false;

    // ── Helpers de UI ─────────────────────────────────────────────

    /** Formata segundos em string legível (ex: "6h 30min" ou "2 dias 4h"). */
    function _formatarTempoRestante(segundos) {
        if (segundos <= 0) return 'Expirado';
        var horas = Math.floor(segundos / 3600);
        var minutos = Math.floor((segundos % 3600) / 60);
        if (horas >= 48) {
            var dias = Math.floor(horas / 24);
            var hRest = horas % 24;
            return dias + 'd ' + (hRest > 0 ? hRest + 'h' : '');
        }
        if (horas > 0) return horas + 'h ' + (minutos > 0 ? minutos + 'min' : '');
        return minutos + 'min';
    }

    /** Atualiza o texto do preview de expiração conforme a seleção do usuário. */
    function _atualizarPreviewExpiracao() {
        var duracaoEl = document.getElementById('limiteDuracaoSelect');
        var customEl  = document.getElementById('limiteCustomHorasInput');
        var textoEl   = document.getElementById('limitePreviewTexto');
        if (!duracaoEl || !textoEl) return;

        var duracao = duracaoEl.value;
        var horas;
        if (duracao === '24h')     horas = 24;
        else if (duracao === '7d') horas = 168;
        else if (duracao === '30d') horas = 720;
        else {
            horas = parseInt(customEl ? customEl.value : 0, 10) || 0;
        }

        if (!horas) {
            textoEl.innerHTML = 'Expira em: <span class="font-bold">—</span>';
            return;
        }

        // Calcula a data estimada de expiração no navegador apenas para preview —
        // a data real será calculada pelo backend com o relógio do servidor.
        var expiracao = new Date(Date.now() + horas * 3600 * 1000);
        var formatado = expiracao.toLocaleDateString('pt-BR', {
            day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
        });
        textoEl.innerHTML = 'Expira em: <span class="font-bold">' + _formatarTempoRestante(horas * 3600) + '</span> &nbsp;·&nbsp; <span class="text-slate-400">' + formatado + '</span>';
    }

    /** Mostra ou oculta o campo de horas customizadas. */
    window.toggleDuracaoCustom = function (valor) {
        var wrap = document.getElementById('limiteDuracaoCustomWrap');
        if (wrap) {
            if (valor === 'custom') {
                wrap.classList.remove('hidden');
            } else {
                wrap.classList.add('hidden');
            }
        }
        _atualizarPreviewExpiracao();
    };

    /** Exibe ou oculta o banner de erro inline. */
    function _mostrarErro(mensagem) {
        var box   = document.getElementById('limiteErroBox');
        var texto = document.getElementById('limiteErroTexto');
        if (!box || !texto) return;
        if (mensagem) {
            texto.textContent = mensagem;
            box.classList.remove('hidden');
        } else {
            box.classList.add('hidden');
            texto.textContent = '';
        }
    }

    // ── Abertura / Fechamento ─────────────────────────────────────

    window.abrirModalLimiteTemporario = function () {
        var modal   = document.getElementById('modalLimiteTemporario');
        var content = document.getElementById('modalLimiteContent');
        if (!modal || !content) return;

        // Limpa campos ao abrir para evitar dados residuais de sessão anterior
        var valorInput = document.getElementById('limiteValorInput');
        var duracaoSel = document.getElementById('limiteDuracaoSelect');
        var customInput = document.getElementById('limiteCustomHorasInput');
        var catSel = document.getElementById('limiteCategoriaSelect');
        if (valorInput) valorInput.value = '';
        if (duracaoSel) duracaoSel.value = '24h';
        if (customInput) customInput.value = '';
        if (catSel) catSel.value = '';

        _mostrarErro(null);
        window.toggleDuracaoCustom('24h');
        _atualizarPreviewExpiracao();

        modal.classList.remove('hidden');
        setTimeout(function () {
            content.classList.remove('scale-95', 'opacity-0');
            content.classList.add('scale-100', 'opacity-100');
            if (valorInput) valorInput.focus();
        }, 10);
        _modalAberto = true;
    };

    window.fecharModalLimiteTemporario = function () {
        var modal   = document.getElementById('modalLimiteTemporario');
        var content = document.getElementById('modalLimiteContent');
        if (!modal || !content) return;

        content.classList.remove('scale-100', 'opacity-100');
        content.classList.add('scale-95', 'opacity-0');
        setTimeout(function () {
            modal.classList.add('hidden');
            _modalAberto = false;
        }, 200);
    };

    // Fecha ao clicar no backdrop
    document.addEventListener('DOMContentLoaded', function () {
        var modal = document.getElementById('modalLimiteTemporario');
        if (modal) {
            modal.addEventListener('click', function (e) {
                if (e.target === modal) window.fecharModalLimiteTemporario();
            });
        }

        // Atualiza preview quando o usuário altera a duração customizada
        var customInput = document.getElementById('limiteCustomHorasInput');
        if (customInput) {
            customInput.addEventListener('input', _atualizarPreviewExpiracao);
        }

        // Inicializa o countdown nos cards de limites já renderizados pelo backend
        _iniciarCountdownsExistentes();
    });

    // ── Salvar Limite (fetch POST) ────────────────────────────────

    /**
     * Envia o formulário via fetch para o endpoint Django.
     * Em caso de sucesso, insere o novo card no DOM sem recarregar a página
     * — mantendo a reatividade do Planejamento.
     */
    window.salvarLimiteTemporario = function () {
        var valorInput  = document.getElementById('limiteValorInput');
        var duracaoSel  = document.getElementById('limiteDuracaoSelect');
        var customInput = document.getElementById('limiteCustomHorasInput');
        var catSel      = document.getElementById('limiteCategoriaSelect');
        var btnSalvar   = document.getElementById('limiteSalvarBtn');
        var btnTexto    = document.getElementById('limiteSalvarTexto');
        var btnIcone    = document.getElementById('limiteSalvarIcone');

        if (!valorInput || !duracaoSel) return;

        _mostrarErro(null);

        var valor   = parseFloat(valorInput.value);
        var duracao = duracaoSel.value;
        var customH = customInput ? parseInt(customInput.value, 10) : 0;

        // Validação client-side básica — o backend valida novamente (Defense in Depth)
        if (!valor || valor <= 0) {
            _mostrarErro('Informe um valor válido maior que zero.');
            valorInput.focus();
            return;
        }
        if (duracao === 'custom' && (!customH || customH <= 0)) {
            _mostrarErro('Informe a quantidade de horas para a duração personalizada.');
            if (customInput) customInput.focus();
            return;
        }

        // Loading state
        if (btnSalvar) btnSalvar.disabled = true;
        if (btnIcone)  btnIcone.className = 'bi bi-arrow-repeat animate-spin pointer-events-none';
        if (btnTexto)  btnTexto.textContent = 'Salvando...';

        var url       = window.HORIZON_LIMITE_CADASTRAR_URL || '/limites-temporarios/cadastrar/';
        var csrfToken = window.HORIZON_CSRF_TOKEN || '';

        var payload = new URLSearchParams({
            valor_limite:          valor,
            duracao:               duracao,
            duracao_custom_horas:  customH || '',
            categoria_alvo:        catSel ? catSel.value : '',
        });

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
            },
            body: payload,
        })
        .then(function (resp) {
            return resp.json().then(function (data) {
                return { ok: resp.ok, data: data };
            });
        })
        .then(function (result) {
            if (!result.ok || result.data.status !== 'ok') {
                _mostrarErro(result.data.mensagem || 'Erro ao salvar. Tente novamente.');
                return;
            }
            // Insere o card do novo limite no DOM sem recarregar a página
            _inserirCardLimite(result.data.limite);
            window.fecharModalLimiteTemporario();
        })
        .catch(function (err) {
            console.error('[LimiteTemporario] Erro de rede:', err);
            _mostrarErro('Falha na conexão. Verifique sua internet e tente novamente.');
        })
        .finally(function () {
            if (btnSalvar) btnSalvar.disabled = false;
            if (btnIcone)  btnIcone.className = 'bi bi-shield-check pointer-events-none';
            if (btnTexto)  btnTexto.textContent = 'Ativar Guardião';
        });
    };

    // ── Desativar Limite (soft-delete) ────────────────────────────

    /**
     * Desativa um limite via POST e remove o card do DOM.
     * Soft-delete preserva o histórico no banco para auditoria futura
     * (o Open Finance precisa saber quais limites estavam ativos em cada período).
     *
     * @param {number} pk - PK do LimiteTemporario no banco.
     */
    window.desativarLimite = function (pk) {
        var card = document.getElementById('cardLimite_' + pk);
        var baseUrl = window.HORIZON_LIMITE_DESATIVAR_BASE_URL || '/limites-temporarios/';
        var url = baseUrl + pk + '/desativar/';
        var csrfToken = window.HORIZON_CSRF_TOKEN || '';

        // Feedback visual imediato: opacidade + escala antes de remover
        if (card) {
            card.style.transition = 'opacity 0.2s, transform 0.2s';
            card.style.opacity    = '0.4';
            card.style.transform  = 'scale(0.97)';
        }

        fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
        })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            if (data.status === 'ok') {
                if (card) {
                    // Remove o card com animação de saída
                    card.style.opacity   = '0';
                    card.style.transform = 'scale(0.9)';
                    setTimeout(function () {
                        card.remove();
                        _verificarListaVazia();
                    }, 200);
                }
            } else {
                // Reverte o feedback visual se houver erro
                if (card) {
                    card.style.opacity   = '1';
                    card.style.transform = 'scale(1)';
                }
                console.error('[LimiteTemporario] Erro ao desativar:', data.mensagem);
            }
        })
        .catch(function (err) {
            if (card) {
                card.style.opacity   = '1';
                card.style.transform = 'scale(1)';
            }
            console.error('[LimiteTemporario] Erro de rede ao desativar:', err);
        });
    };

    // ── Renderização de novo card no DOM ─────────────────────────

    /**
     * Insere o card do limite recém-criado no topo da lista,
     * sem necessidade de reload. O card espelha o HTML do template Django.
     *
     * @param {Object} limite - Objeto retornado pela view Django.
     */
    function _inserirCardLimite(limite) {
        var lista = document.getElementById('listLimitesAtivos');
        var emptyState = document.getElementById('empty-state-guardiao');

        if (lista) {
            lista.classList.remove('hidden');
        }
        if (emptyState) {
            emptyState.classList.add('hidden');
        }

        var categoriaTexto = limite.categoria_nome || 'Geral';
        var tempoFmt = _formatarTempoRestante(limite.tempo_restante_segundos);
        var barWidth = Math.min(limite.percentual || 0, 100);

        var html = [
            '<article id="cardLimite_' + limite.id + '"',
            '         class="card-dark rounded-3xl p-5 border border-slate-800 transition-all duration-300 hover:border-amber-500/30 flex flex-col',
            '                opacity-0 scale-95" style="transition: opacity 0.3s, transform 0.3s;">',
            '  <div class="flex items-start justify-between gap-3 mb-4">',
            '    <div class="flex items-center gap-3 flex-1 min-w-0">',
            '      <div class="h-10 w-10 rounded-xl bg-amber-500/10 flex items-center justify-center shrink-0">',
            '        <i class="bi bi-stopwatch text-amber-400 text-lg"></i>',
            '      </div>',
            '      <div class="flex-1 min-w-0">',
            '        <p class="text-base font-black text-slate-200 truncate">',
            '          R$ ' + Number(limite.valor_limite).toLocaleString('pt-BR', {minimumFractionDigits: 2}),
            '          <span class="text-slate-500 font-normal text-sm">→ ' + _escaparHtml(categoriaTexto) + '</span>',
            '        </p>',
            '        <p class="text-[10px] font-bold text-slate-500 mt-0.5 truncate uppercase tracking-widest">Expira em: ' + tempoFmt + '</p>',
            '      </div>',
            '    </div>',
            '  </div>',
            '  <div class="mt-auto">',
            '    <div class="flex items-center justify-between mb-2">',
            '      <span class="text-xs font-black ' + (limite.cor_status || 'text-emerald-400') + '">',
            '        ' + (limite.percentual || 0) + '% consumido',
            '      </span>',
            '      <button type="button" onclick="desativarLimite(' + limite.id + ')"',
            '          class="h-7 w-7 rounded-lg bg-slate-800/60 text-slate-500 hover:text-red-400',
            '                 hover:bg-red-500/10 flex items-center justify-center transition-colors"',
            '          title="Cancelar este limite">',
            '        <i class="bi bi-x-lg text-xs pointer-events-none"></i>',
            '      </button>',
            '    </div>',
            '    <div class="w-full bg-slate-800 rounded-full h-2 overflow-hidden shadow-inner">',
            '      <div class="' + (limite.cor_barra || 'bg-cyan-500') + ' h-full rounded-full transition-all duration-500"',
            '           style="width: ' + barWidth + '%;"></div>',
            '    </div>',
            '    <p class="text-[10px] text-slate-600 mt-3 flex items-center gap-1.5 bg-[#0f172a] p-2 rounded-lg">',
            '      <i class="bi bi-info-circle text-amber-500/50"></i>',
            '      Consumo automático em breve via Open Finance.',
            '    </p>',
            '  </div>',
            '</article>',
        ].join('\n');

        // Insere antes dos outros cards (mais recente no topo)
        lista.insertAdjacentHTML('afterbegin', html);

        // Anima entrada
        var novoCard = document.getElementById('cardLimite_' + limite.id);
        if (novoCard) {
            requestAnimationFrame(function () {
                novoCard.style.opacity   = '1';
                novoCard.style.transform = 'scale(1)';
            });
        }
    }

    /** Escapa HTML para evitar XSS ao inserir dados de resposta da API no DOM. */
    function _escaparHtml(texto) {
        var div = document.createElement('div');
        div.textContent = String(texto || '');
        return div.innerHTML;
    }

    /** Verifica se a lista ficou vazia após remover um card e exibe o estado vazio. */
    function _verificarListaVazia() {
        var lista = document.getElementById('listLimitesAtivos');
        var emptyState = document.getElementById('empty-state-guardiao');
        if (lista && lista.children.length === 0) {
            lista.classList.add('hidden');
            if (emptyState) {
                emptyState.classList.remove('hidden');
            }
        }
    }

    // ── Countdown nos cards existentes (renderizados pelo Django) ─

    /**
     * Inicia um setInterval para atualizar o texto de tempo restante
     * nos cards de limites que já foram renderizados pelo backend.
     * O intervalo é de 60s para não impactar performance.
     */
    function _iniciarCountdownsExistentes() {
        var timers = document.querySelectorAll('[id^="timerLimite_"]');
        if (!timers.length) return;

        function atualizarTimers() {
            timers.forEach(function (el) {
                var fimStr = el.getAttribute('data-fim');
                if (!fimStr) return;
                var segundos = Math.floor((new Date(fimStr) - Date.now()) / 1000);
                if (segundos <= 0) {
                    el.textContent = '⚠️ Expirado';
                    el.className = el.className.replace('text-slate-500', 'text-amber-500');
                } else {
                    el.textContent = 'Expira em: ' + _formatarTempoRestante(segundos);
                }
            });
        }

        atualizarTimers();
        setInterval(atualizarTimers, 60000); // Atualiza a cada 1 minuto
    }

})();
