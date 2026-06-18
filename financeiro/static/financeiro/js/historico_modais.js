/**
 * historico_modais.js
 * Motor de reclassificação retroativa para o Extrato (historico.html).
 *
 * Depende de:
 *   - window.HORIZON_CATEGORIAS: objeto JSON injetado pelo template com estrutura:
 *       { macros: [{id, nome, tipo}], subcategorias: [{id, nome, macro_id}] }
 *   - window.HORIZON_URLS.reclassificar: URL do endpoint AJAX (injetado pelo template)
 */

(function () {
  'use strict';

  // ─── Estado interno ──────────────────────────────────────────
  let transacaoAtualId = null;
  let transacaoAtualTipo = null;

  // ─── Referências ao DOM ───────────────────────────────────────
  const modal         = document.getElementById('modalReclassificacao');
  const overlay       = document.getElementById('overlay-reclassificacao');
  const btnClose      = document.getElementById('btn-close-reclassificacao');
  const btnCancelar   = document.getElementById('btn-cancelar-reclassificacao');
  const btnConfirmar  = document.getElementById('btn-confirmar-reclassificacao');
  const btnLabel      = document.getElementById('btn-confirmar-label');
  const btnSpinner    = document.getElementById('btn-confirmar-spinner');
  const elDescricao   = document.getElementById('modal-descricao');
  const elValor       = document.getElementById('modal-valor');
  const selectMacro   = document.getElementById('select-macro');
  const selectSub     = document.getElementById('select-subcategoria');
  const chkLote       = document.getElementById('chk-aplicar-lote');

  if (!modal) return; // Página sem o modal → sai silenciosamente

  // ─── CSRF helper ─────────────────────────────────────────────
  function getCsrfToken() {
    const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return cookie ? cookie.trim().split('=')[1] : '';
  }

  // ─── Utilitários de visibilidade ─────────────────────────────
  function abrirModal() {
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function fecharModal() {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
    resetarModal();
  }

  function resetarModal() {
    transacaoAtualId   = null;
    transacaoAtualTipo = null;
    elDescricao.textContent = '—';
    elValor.textContent     = '—';
    selectMacro.innerHTML   = '<option value="">Selecione uma macro categoria…</option>';
    selectSub.innerHTML     = '<option value="">Primeiro selecione a macro…</option>';
    selectSub.disabled      = true;
    chkLote.checked         = false;
    setBotaoConfirmar(false);
  }

  function setBotaoConfirmar(enabled) {
    btnConfirmar.disabled = !enabled;
  }

  function setCarregando(loading) {
    btnLabel.classList.toggle('hidden', loading);
    btnSpinner.classList.toggle('hidden', !loading);
    btnConfirmar.disabled = loading;
  }

  // ─── População dos selects ────────────────────────────────────
  function popularMacros(tipo) {
    const dados = (window.HORIZON_CATEGORIAS || {}).macros || [];
    selectMacro.innerHTML = '<option value="">Selecione uma macro categoria…</option>';

    // Saídas genéricas incluem tanto 'despesa' quanto 'reservado' para
    // permitir reclassificação direta como reserva/investimento
    const tiposAceitos = (tipo === 'despesa' || tipo === 'reservado')
      ? ['despesa', 'reservado']
      : [tipo];

    dados
      .filter(m => tiposAceitos.includes(m.tipo))
      .forEach(m => {
        const opt = document.createElement('option');
        opt.value       = m.id;
        opt.textContent = m.nome;
        selectMacro.appendChild(opt);
      });
  }

  function popularSubcategorias(macroId) {
    const dados = (window.HORIZON_CATEGORIAS || {}).subcategorias || [];
    selectSub.innerHTML = '<option value="">Selecione a subcategoria…</option>';
    selectSub.disabled  = true;
    setBotaoConfirmar(false);

    const subs = dados.filter(s => String(s.macro_id) === String(macroId));
    if (!subs.length) {
      selectSub.innerHTML = '<option value="">Nenhuma subcategoria disponível</option>';
      return;
    }

    subs.forEach(s => {
      const opt = document.createElement('option');
      opt.value       = s.id;
      opt.textContent = s.nome;
      selectSub.appendChild(opt);
    });
    selectSub.disabled = false;
  }

  // ─── API pública: chamada pelo onclick do botão de engrenagem ─
  window.abrirReclassificacao = function (btn) {
    const id       = btn.dataset.id;
    const descricao = btn.dataset.descricao;
    const valor    = btn.dataset.valor;
    const tipo     = btn.dataset.tipo;   // 'receita' | 'despesa' | 'reservado'

    transacaoAtualId   = id;
    transacaoAtualTipo = tipo;

    elDescricao.textContent = descricao;
    elValor.textContent     = valor;

    popularMacros(tipo);
    selectSub.innerHTML = '<option value="">Primeiro selecione a macro…</option>';
    selectSub.disabled  = true;
    chkLote.checked     = false;
    setBotaoConfirmar(false);

    abrirModal();
  };

  // ─── Encadeamento: macro → sub ────────────────────────────────
  selectMacro.addEventListener('change', function () {
    const macroId = this.value;
    if (macroId) {
      popularSubcategorias(macroId);
    } else {
      selectSub.innerHTML = '<option value="">Primeiro selecione a macro…</option>';
      selectSub.disabled  = true;
      setBotaoConfirmar(false);
    }
  });

  selectSub.addEventListener('change', function () {
    setBotaoConfirmar(!!this.value);
  });

  // ─── Submit AJAX ──────────────────────────────────────────────
  btnConfirmar.addEventListener('click', async function () {
    const categoriaId  = selectSub.value;
    const aplicarLote  = chkLote.checked;

    if (!categoriaId || !transacaoAtualId) return;

    setCarregando(true);

    try {
      const url = (window.HORIZON_URLS || {}).reclassificar || '/financeiro/api/reclassificar/';

      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
          transacao_id: transacaoAtualId,
          categoria_id: categoriaId,
          aplicar_lote: aplicarLote,
        }),
      });

      const data = await resp.json();

      if (resp.ok && data.status === 'success') {
        fecharModal();
        location.reload();
      } else {
        alert('Erro ao reclassificar: ' + (data.mensagem || 'tente novamente.'));
        setCarregando(false);
      }
    } catch (err) {
      alert('Falha de conexão. Verifique sua internet e tente novamente.');
      setCarregando(false);
    }
  });

  // ─── Excluir Transação AJAX ──────────────────────────────────
  window.excluirTransacaoAtual = async function () {
    try {
      console.log("-> Função excluirTransacaoAtual() disparada.");
      console.log("-> ID atual capturado:", transacaoAtualId);

      if (!transacaoAtualId) {
        console.error("ERRO: ID da transação não encontrado no escopo do JS!");
        alert("Erro interno: Transação não identificada.");
        return;
      }

      if (!confirm("Tem certeza que deseja excluir esta transação?")) {
        return;
      }

      const url = `/api/excluir/${transacaoAtualId}/`;
      console.log("-> Disparando fetch POST para:", url);

      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        }
      });

      if (!resp.ok) {
        console.error("Erro na requisição. Status:", resp.status);
        alert("Erro de comunicação com o servidor ao excluir a transação.");
        return;
      }

      const data = await resp.json();
      console.log("-> Resposta da API:", data);

      if (resp.ok && data.status === 'success') {
        // Remove a linha dinamicamente
        const btnReclassificar = document.querySelector(`button[data-id="${transacaoAtualId}"]`);
        if (btnReclassificar) {
          const row = btnReclassificar.closest('article');
          if (row) {
            row.remove();
            console.log("-> Linha HTML removida com sucesso.");
          }
        }
        
        fecharModal();
      } else {
        alert('Erro ao excluir: ' + (data.mensagem || 'tente novamente.'));
      }
    } catch (err) {
      console.error("ERRO GRAVE no fluxo de exclusão:", err);
      alert('Falha de conexão ou erro no Javascript. Verifique o console.');
    }
  };

  // ─── Fechamento do modal ──────────────────────────────────────
  [overlay, btnClose, btnCancelar].forEach(el => {
    el && el.addEventListener('click', fecharModal);
  });

  // Fechar com Escape
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
      fecharModal();
    }
  });
})();
