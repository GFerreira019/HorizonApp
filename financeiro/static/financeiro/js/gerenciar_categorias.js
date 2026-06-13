/**
 * Gerenciamento dinâmico de subcategorias (adicionar, editar, excluir via AJAX).
 * Funciona de forma integrada com os modais de Nova Conta Fixa e Nova Receita Planejada.
 */
(function () {
    'use strict';

    var currentMacroId = null;

    function getCsrfToken() {
        var input = document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    /**
     * Tenta identificar o ID e Nome da macro categoria ativa com base nos modais abertos no momento.
     */
    function getActiveMacroIdAndNome() {
        var despesaModal = document.getElementById('modalNovaDespesa');
        var receitaModal = document.getElementById('modalNovaReceitaPlanejada');

        // Se o modal de nova despesa estiver aberto
        if (despesaModal && !despesaModal.classList.contains('hidden')) {
            var macroInput = document.getElementById('macroIdNovaDespesa');
            if (macroInput && macroInput.value) {
                var macroId = macroInput.value;
                var macroNome = window.currentMacroNome || '';
                if (!macroNome) {
                    var select = document.getElementById('categoriaNovaDespesa');
                    var opt = select ? select.querySelector('option[data-macro-id="' + macroId + '"]') : null;
                    if (opt) {
                        var text = opt.textContent;
                        var parts = text.split('>');
                        if (parts.length > 1) macroNome = parts[0].trim();
                    }
                }
                return { id: macroId, nome: macroNome };
            } else {
                var select = document.getElementById('categoriaNovaDespesa');
                var opt = select ? select.options[select.selectedIndex] : null;
                if (opt && opt.value) {
                    var macroId = opt.getAttribute('data-macro-id');
                    var text = opt.textContent;
                    var parts = text.split('>');
                    var macroNome = parts.length > 1 ? parts[0].trim() : '';
                    return { id: macroId, nome: macroNome };
                }
            }
        }

        // Se o modal de receita planejada estiver aberto
        if (receitaModal && !receitaModal.classList.contains('hidden')) {
            var macroInput = document.getElementById('macroIdNovaReceita');
            if (macroInput && macroInput.value) {
                var macroId = macroInput.value;
                var macroNome = window.currentMacroNome || '';
                if (!macroNome) {
                    var select = document.getElementById('categoriaNovaReceita');
                    var opt = select ? select.querySelector('option[data-macro-id="' + macroId + '"]') : null;
                    if (opt) {
                        var text = opt.textContent;
                        var parts = text.split('>');
                        if (parts.length > 1) macroNome = parts[0].trim();
                    }
                }
                return { id: macroId, nome: macroNome };
            } else {
                var select = document.getElementById('categoriaNovaReceita');
                var opt = select ? select.options[select.selectedIndex] : null;
                if (opt && opt.value) {
                    var macroId = opt.getAttribute('data-macro-id');
                    var text = opt.textContent;
                    var parts = text.split('>');
                    var macroNome = parts.length > 1 ? parts[0].trim() : '';
                    return { id: macroId, nome: macroNome };
                }
            }
        }

        return null;
    }

    window.abrirModalGerenciarCategorias = function () {
        var macroInfo = getActiveMacroIdAndNome();
        if (!macroInfo || !macroInfo.id) {
            alert('Selecione uma categoria primeiro no formulário para gerenciar suas subcategorias.');
            return;
        }

        currentMacroId = macroInfo.id;
        window.currentMacroNome = macroInfo.nome;

        // Atualiza o título do modal
        var titulo = document.getElementById('gerenciarCategoriasTitulo');

        if (titulo) {
            titulo.textContent = macroInfo.nome || 'Subcategorias';
        }

        // Exibe o modal
        var modal = document.getElementById('modalGerenciarCategorias');
        if (modal) modal.classList.remove('hidden');

        // Limpa erros e inputs
        var input = document.getElementById('novaCategoriaNomeInput');
        if (input) input.value = '';
        
        var errorEl = document.getElementById('erroAdicionarCategoria');
        if (errorEl) {
            errorEl.classList.add('hidden');
            errorEl.textContent = '';
        }

        // Carrega a lista de categorias do backend
        carregarCategorias();
    };

    window.fecharModalGerenciarCategorias = function () {
        var modal = document.getElementById('modalGerenciarCategorias');
        if (modal) modal.classList.add('hidden');
    };

    async function carregarCategorias() {
        var container = document.getElementById('listaCategoriasGerenciamento');
        if (!container) return;
        
        container.innerHTML = '<div class="text-center text-slate-500 py-6 text-xs"><i class="bi bi-arrow-repeat animate-spin text-lg text-cyan-500 block mb-1"></i> Carregando...</div>';

        try {
            var response = await fetch('/categorias/criar/?macro_categoria_id=' + currentMacroId);
            var data = await response.json();
            
            if (data.status === 'ok') {
                renderListaCategorias(data.categorias);
            } else {
                container.innerHTML = '<p class="text-red-400 text-xs text-center py-4">Erro ao carregar categorias.</p>';
            }
        } catch (e) {
            container.innerHTML = '<p class="text-red-400 text-xs text-center py-4">Erro de conexão.</p>';
        }
    }

    function renderListaCategorias(categorias) {
        var container = document.getElementById('listaCategoriasGerenciamento');
        if (!container) return;
        
        container.innerHTML = '';

        if (categorias.length === 0) {
            container.innerHTML = '<p class="text-slate-500 text-xs text-center py-6">Nenhuma subcategoria cadastrada para esta macro.</p>';
            return;
        }

        categorias.forEach(function (cat) {
            var div = document.createElement('div');
            div.className = 'flex justify-between items-center p-2.5 bg-slate-900 border border-slate-800 rounded-xl gap-2 group';
            
            // Modo Visualização
            var viewDiv = document.createElement('div');
            viewDiv.className = 'flex-1 min-w-0 flex items-center justify-between w-full';
            viewDiv.id = 'cat-view-' + cat.id;

            var span = document.createElement('span');
            span.className = 'text-xs text-slate-200 truncate font-semibold';
            span.textContent = cat.nome;
            viewDiv.appendChild(span);

            var actionsDiv = document.createElement('div');
            actionsDiv.className = 'flex items-center gap-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity';

            // Botão Editar
            var editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'text-slate-400 hover:text-cyan-400 transition-colors p-1';
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.onclick = function () {
                enableEditMode(cat.id, cat.nome);
            };
            actionsDiv.appendChild(editBtn);

            // Botão Excluir
            var deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'text-slate-400 hover:text-red-400 transition-colors p-1';
            deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
            deleteBtn.onclick = function () {
                excluirCategoria(cat.id, cat.nome);
            };
            actionsDiv.appendChild(deleteBtn);

            viewDiv.appendChild(actionsDiv);
            div.appendChild(viewDiv);

            // Modo Edição (escondido por padrão)
            var editForm = document.createElement('form');
            editForm.className = 'flex-1 flex gap-2 hidden';
            editForm.id = 'cat-edit-form-' + cat.id;
            editForm.onsubmit = function (e) {
                e.preventDefault();
                salvarEdicao(cat.id);
            };

            var input = document.createElement('input');
            input.type = 'text';
            input.className = 'flex-1 bg-[#151e32] text-white border border-slate-700 rounded-lg px-2.5 py-1 text-xs outline-none';
            input.value = cat.nome;
            input.id = 'cat-edit-input-' + cat.id;
            editForm.appendChild(input);

            var saveBtn = document.createElement('button');
            saveBtn.type = 'submit';
            saveBtn.className = 'text-emerald-400 hover:text-emerald-300 font-bold text-xs px-1.5 py-1';
            saveBtn.innerHTML = '<i class="bi bi-check-lg text-sm"></i>';
            editForm.appendChild(saveBtn);

            var cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'text-slate-400 hover:text-white text-xs px-1.5 py-1';
            cancelBtn.innerHTML = '<i class="bi bi-x-lg text-xs"></i>';
            cancelBtn.onclick = function () {
                disableEditMode(cat.id);
            };
            editForm.appendChild(cancelBtn);

            div.appendChild(editForm);
            container.appendChild(div);
        });
    }

    function enableEditMode(id, nome) {
        var viewEl = document.getElementById('cat-view-' + id);
        if (viewEl) viewEl.classList.add('hidden');
        
        var formEl = document.getElementById('cat-edit-form-' + id);
        if (formEl) formEl.classList.remove('hidden');
        
        var inputEl = document.getElementById('cat-edit-input-' + id);
        if (inputEl) {
            inputEl.value = nome;
            inputEl.focus();
        }
    }

    function disableEditMode(id) {
        var formEl = document.getElementById('cat-edit-form-' + id);
        if (formEl) formEl.classList.add('hidden');
        
        var viewEl = document.getElementById('cat-view-' + id);
        if (viewEl) viewEl.classList.remove('hidden');
    }

    async function salvarEdicao(id) {
        var input = document.getElementById('cat-edit-input-' + id);
        var novoNome = input ? (input.value || '').trim() : '';
        if (!novoNome) return;

        try {
            var response = await fetch('/categorias/' + id + '/editar/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ nome: novoNome })
            });
            var data = await response.json();
            if (data.status === 'ok') {
                atualizarTudo(data.categorias);
                renderListaCategorias(data.categorias);
            } else {
                alert(data.mensagem || 'Erro ao editar categoria.');
            }
        } catch (e) {
            alert('Erro de conexão.');
        }
    }

    async function excluirCategoria(id, nome) {
        if (!confirm('Deseja excluir a subcategoria "' + nome + '"?\nNota: Os lançamentos passados continuarão preservados.')) {
            return;
        }

        try {
            var response = await fetch('/categorias/' + id + '/excluir/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            });
            var data = await response.json();
            if (data.status === 'ok') {
                atualizarTudo(data.categorias);
                renderListaCategorias(data.categorias);
            } else {
                alert(data.mensagem || 'Erro ao excluir categoria.');
            }
        } catch (e) {
            alert('Erro de conexão.');
        }
    }

    function atualizarTudo(categorias) {
        if (typeof window.recarregarCategoriasDespesa === 'function') {
            window.recarregarCategoriasDespesa(categorias, currentMacroId);
        }
        if (typeof window.recarregarCategoriasReceita === 'function') {
            window.recarregarCategoriasReceita(categorias, currentMacroId);
        }
    }

    // Inicialização do formulário de adicionar categoria
    document.addEventListener('DOMContentLoaded', function () {
        var formAdd = document.getElementById('formAdicionarCategoria');
        if (formAdd) {
            formAdd.addEventListener('submit', async function (e) {
                e.preventDefault();
                var input = document.getElementById('novaCategoriaNomeInput');
                var nome = input ? (input.value || '').trim() : '';
                if (!nome) return;

                var errorEl = document.getElementById('erroAdicionarCategoria');
                if (errorEl) errorEl.classList.add('hidden');

                try {
                    var response = await fetch('/categorias/criar/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken()
                        },
                        body: JSON.stringify({
                            nome: nome,
                            macro_categoria_id: currentMacroId
                        })
                    });
                    var data = await response.json();
                    if (data.status === 'ok') {
                        if (input) input.value = '';
                        atualizarTudo(data.categorias);
                        renderListaCategorias(data.categorias);
                    } else {
                        if (errorEl) {
                            errorEl.textContent = data.mensagem || 'Erro ao adicionar categoria.';
                            errorEl.classList.remove('hidden');
                        }
                    }
                } catch (err) {
                    if (errorEl) {
                        errorEl.textContent = 'Erro de conexão.';
                        errorEl.classList.remove('hidden');
                    }
                }
            });
        }
    });

})();
