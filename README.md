# 💲 HorizonAPP
> Uma plataforma inteligente para prever o futuro financeiro, não apenas registrar o passado.

---

## 🎯 1. Objetivo do Sistema
Diferente de apps tradicionais de "entradas e saídas", este sistema é focado em **Previsibilidade, Fluxo de Caixa e Planejamento Ativo**.

* **Zero-Based Budgeting:** Cada centavo da sua receita tem um destino planejado antes do mês começar (*Pay Yourself First*).
* **Expectativa vs. Realidade:** Cruza o orçamento planejado com o extrato real em tempo real.
* **Carry-over (Rolagem):** Passivos não pagos acumulam automaticamente para o próximo mês, garantindo que você nunca perca de vista uma dívida.
* **Automação:** Categorização inteligente de dados via Regex e vinculação de transações passadas a custos fixos.
* **Mobile-First:** Experiência otimizada, design simétrico e interface em *Dark Mode* nativo.

---

## 🛠️ 2. Arquitetura e Stack Tecnológico

| Camada | Tecnologia |
| :--- | :--- |
| **Back-end** | Python 3 + Django 5 |
| **Banco de Dados** | SQLite (Desenvolvimento/Relacional) |
| **Front-end** | HTML5 + Django Templates + JavaScript (ES6) |
| **Estilização** | Tailwind CSS (*Dark Mode*) |
| **Gráficos & UI** | Chart.js, Select2, Bootstrap Icons |
| **Localização** | pt-br / America/Sao_Paulo |

---

## 🏗️ 3. Estrutura de Dados (Models)
A arquitetura foi desenhada para garantir linhagem de dados (*Data Lineage*) e um motor de cálculo robusto.

* 🌐 **MacroCategoria:** Agrupador de alto nível (Receita, Despesa, Reservado).
* 📂 **Categoria:** Subdivisões atreladas a ícones específicos e regras de negócio.
* 📦 **Lote de Importação:** Rastreia a origem dos dados (arquivos CSV) para auditoria segura.
* 💸 **Transação:** A tabela de "Fatos". Onde a realidade financeira acontece.
* 🧠 **Regra de Classificação:** O motor de IA/Automação que categoriza gastos via palavras-chave.
* 📅 **Despesa Fixa:** Contratos, prazos e obrigações mensais provisionadas.
* 🎯 **PlanejamentoMensal & OrcamentoCategoria:** Motor relacional que armazena a expectativa de receitas e os limites de gastos configurados pelo usuário para cada mês.

---

## 🚀 4. Funcionalidades Principais

### 📥 Importação e ETL Inteligente
* **Upload de Extrato Bancário:** Conversão automática de CSV para o banco de dados.
* **Classificação Automática:** O sistema aprende a identificar compras e atribui categorias sem intervenção manual.
* **Efeito Cascata Seguro:** Exclua um lote inteiro de importação por engano e todas as transações vinculadas serão removidas automaticamente.

### 📈 Dashboard Inteligente e Histórico
* **MTD (*Month-to-Date*):** Por padrão, as visões priorizam o escopo do mês atual.
* **Cards Interativos:** Os cartões de Entradas, Saídas e Reservas no Dashboard atuam como atalhos de filtros dinâmicos para a tela de histórico.
* **Gráficos Dinâmicos:** Visão de fluxo de caixa em rosca (*Doughnut*) e linha do tempo integrados nativamente.

### 🥧 Planejamento Avançado (*Zero-Based Budgeting*)
* **Motor de Conversão Bidirecional:** Converta valores absolutos (R$) para percentuais (%) do orçamento instantaneamente no frontend.
* **Configuração de Escopo Modular:** Um pop-up flutuante permite ligar/desligar (*Toggle*) quais categorias farão parte do orçamento do mês, limpando a tela de inputs desnecessários.
* **Gestão de Contas Integrada:** Os custos fixos provisionados ficam lado a lado com a distribuição orçamentária, garantindo foco no que falta pagar.
* **Proteção Visual:** Alertas de *over-budget* (vermelho), *perfect-budget* (verde) e *under-budget* (ciano) com barras de progresso ao vivo.

### ⚙️ Controladoria de Custos Fixos
* **Provisionamento Dinâmico:** Cadastro de despesas fixas sem a necessidade de gerar "transações fantasmas" no banco de dados.
* **Vínculo Retroativo:** Um modal de busca permite procurar transações antigas via API para vinculá-las como padrão de uma despesa fixa.

### 📱 Experiência do Usuário (UI/UX)
* **Bottom Navigation Simétrica:** Grid inferior de 7 posições com botão FAB de Adicionar `(+)` geometricamente travado no centro.
* **Notificações Globais:** Toasts animados e indicadores visuais (🔴) sobre pendências de auditoria.

---

## 🗺️ 5. Roadmap de Evolução

**📍 Fase 1: Fundação & ETL (V1.0)**
- [x] Motor de importação CSV.
- [x] Categorização automatizada por regex.
- [x] Histórico e Dashboard relacional.

**📍 Fase 2: Automação Contínua (V2.0)**
- [x] Vínculos lógicos de custos fixos e provisionamento.
- [x] Adição do tipo Reservado para blindar o cálculo de investimentos.
- [ ] Open Finance: Integração direta com APIs bancárias (Substituição do CSV).
- [ ] Saldo de Segurança Diário: Cotas dinâmicas de gastos baseadas nos dias restantes do mês.

**📍 Fase 3: Planejamento & Estratégia (V3.0)**
- [x] Módulo "Pay Yourself First": Orçamento *Zero-Based* (Planejamento Ativo).
- [x] Interface modular de escopo de planejamento com abas e blocos toggle.
- [ ] Simulador de Stress: "E se eu comprar um carro?" - Teste o impacto de novas dívidas no fluxo de 36 meses.
- [ ] Projeção de Liberdade Financeira: Calculadora de juros compostos integrada à meta de aportes.

---

> ✨ *Desenvolvido para quem busca controle absoluto sobre o próprio futuro financeiro.*