# 💲 HorizonAPP
> Uma plataforma inteligente para prever o futuro financeiro, não apenas registrar o passado.

---

## 🎯 1. Objetivo do Sistema
Diferente de apps tradicionais de "entradas e saídas", este sistema é focado em **Previsibilidade e Fluxo de Caixa**. 

* **Expectativa vs. Realidade:** Cruza o orçamento planejado com o extrato real.
* **Mobile-First:** Experiência otimizada para uso em dispositivos móveis.
* **Carry-over (Rolagem):** Passivos não pagos acumulam automaticamente para o próximo mês, garantindo que você nunca perca de vista uma dívida.
* **Automação:** Categorização inteligente de dados via Regex.

---

## 🛠️ 2. Arquitetura e Stack Tecnológico

| Camada | Tecnologia |
| :--- | :--- |
| **Back-end** | `Python 3` + `Django 5` |
| **Banco de Dados** | `SQLite` (Desenvolvimento/Relacional) |
| **Front-end** | `HTML5` + `Django Templates` |
| **Estilização** | `Tailwind CSS` (Dark Mode Nativo) |
| **Ícones & UI** | `Bootstrap Icons` |
| **Localização** | `pt-br` / `America/Sao_Paulo` |

---

## 🏗️ 3. Estrutura de Dados (Models)
A arquitetura foi desenhada para garantir **linhagem de dados (Data Lineage)** e integridade total.

* 📂 **Categoria:** Define se o fluxo é Receita ou Despesa (Alimentação, Transporte, etc).
* 📦 **Lote de Importação:** Rastreia a origem dos dados (arquivos CSV) para auditoria.
* 💸 **Transação:** A tabela de "Fatos". Onde a realidade financeira acontece.
* 🧠 **Regra de Classificação:** O motor de IA/Automação que categoriza gastos via palavras-chave.
* 📅 **Despesa Fixa:** A tabela de "Expectativa". Define contratos, prazos e orçamentos mensais.

---

## 🚀 4. Funcionalidades Principais

### 📥 Importação e ETL Inteligente
- **Upload de Extrato Bancário:** Conversão automática de CSV para o banco de dados.
- **Classificação Automática:** O sistema aprende a identificar compras e atribui categorias sem intervenção manual.
- **Prevenção de Duplicatas:** Algoritmo de segurança para evitar importar a mesma transação duas vezes.
- **Efeito Cascata:** Exclua um lote inteiro de importação por engano e todas as transações vinculadas serão removidas automaticamente.

### 🔍 Auditoria e Conciliação
- **Painel de Revisão:** Interface para validar transações duvidosas ou na categoria "Outros".
- **Notificação Global:** Um indicador visual (🔴) alerta em todas as telas sobre pendências de auditoria.

### 🕒 Histórico e Timeline
- **Visual Bancário:** Transações agrupadas por blocos temporais (Hoje, Ontem, etc).
- **Filtros Dinâmicos:** Modal para busca rápida por range de datas (Padrão: últimos 7 dias).

### 📊 Controladoria e Orçamento
- **Contratos Automatizados:** Marque uma despesa como "fixa" e o sistema provisiona os próximos meses.
- **Algoritmo Carry-over:** Dívidas vencidas são transferidas como fardo financeiro para o mês atual, impedindo a "maquiagem" de saldos.
- **Status Visual:** Acompanhamento preciso entre *Pago*, *Pendente* e *Atrasado*.

### 📱 Experiência do Usuário (UI/UX)
- **Bottom Navigation Bar:** Navegação rápida com o polegar.
- **Floating Action Button (FAB):** Botão central para lançamentos rápidos de qualquer lugar.

---

## 🗺️ 5. Roadmap de Evolução

### 📍 Fase 2: Automação Contínua (V2.0)
- [ ] **Open Finance:** Integração direta com APIs bancárias (fim do CSV).
- [ ] **Budgeting Ativo:** Divisão do orçamento em cotas diárias/semanais.
- [ ] **Saldo de Segurança:** Alertas em tempo real sobre o comprometimento da meta do mês.

### 📍 Fase 3: Planejamento Avançado (V3.0)
- [ ] **Módulo "Pay Yourself First":** Planejamento estratégico antes do mês começar.
- [ ] **Simulador de Stress:** "E se eu comprar um carro?" - Teste o impacto de novas dívidas no fluxo de 36 meses.
- [ ] **Projeção de Liberdade Financeira:** Calculadora de juros compostos integrada aos seus gastos reais.

---
✨ *Desenvolvido para quem busca controle absoluto sobre o próprio futuro financeiro.*