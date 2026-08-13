# Active tasks

> Брать СВЕРХУ. Внутри приоритета — сверху вниз.
> Перед изменением статуса — `brain-lock acquire <id> --as <agent-id>`.

## P0

## P1
- [ ] [P1] t-2026-05-01-bootstrap-wiki — Заполнить wiki стартовыми страницами
      role: linter   mode: solo
      acceptance: в wiki/index.md есть категории и хотя бы 5 страниц.

- [ ] [P1] t-2026-05-01-pick-llm-stack — Выбрать стек моделей под роли
      role: architect   mode: council
      council: [architect, reviewer, researcher]
      Какие модели на какие роли поставить, исходя из бюджета и провайдеров.
      acceptance: wiki/decision-llm-stack.md с обоснованием и таблицей.

## P2
- [ ] [P2] t-2026-05-01-cli-cheatsheet — Шпаргалка CLI-агентов в wiki
      role: researcher   mode: solo
      acceptance: wiki/cli-agents.md с таблицей и примерами.

- [ ] [P2] t-2026-05-01-council-legal-example — Шаблон договора услуг для ИП
      role: lawyer   mode: council
      council: [team:legal]
      Нужен ли акт ежемесячно? Какой режим (услуги/подряд/заказ ПО)?
      acceptance: проект договора + правовое заключение в wiki/decision-services-contract.md.

- [ ] [P2] t-2026-05-01-council-marketing-example — Запуск AI-консалтинга
      role: strategist   mode: council
      council: [team:marketing]
      Позиционирование, 2 ICP, 2 канала, юнит-экономика на 6 мес.
      acceptance: wiki/decision-gtm-ai-consulting.md с числами.

- [ ] [P2] t-2026-05-01-council-pm-example — Запуск нового направления Y
      role: product   mode: council
      council: [team:pm]
      acceptance: PRD + roadmap на 6 мес + status report template.

- [ ] [P1] t-2026-05-01-council-finance-example — Выбрать налоговый режим
      role: tax-advisor   mode: council
      council: [team:finance]
      Доход прогноз ~3-5 млн/год, фриланс + иностранные клиенты, ИП.
      acceptance: wiki/decision-tax-regime.md с расчётом по 4 режимам и cashflow на год.

- [ ] [P2] t-2026-05-01-council-creative-example — Лендинг для AI-консалтинга
      role: strategist   mode: council
      council: [team:creative, growth-analyst]
      acceptance: wireframe + текст + design rationale + предсказание конверсии.

- [ ] [P1] t-2026-05-01-council-negotiation-example — Подготовка к крупному контракту
      role: negotiator   mode: council
      council: [team:negotiation]
      Контракт на 6 мес, $X/мес, 2 раунда переговоров.
      acceptance: negotiation prep документ + проект договора + cashflow impact.

- [ ] [P1] t-2026-05-01-tax-edge-case — Самозанятый-разработчик: можно ли работать?
      role: tax-advisor   mode: council
      council: [tax-advisor, lawyer]
      Контекст: ИП на УСН-6 хочет нанять разработчика как самозанятого на 100k/мес
      на 6+ месяцев. Риск переквалификации в трудовые отношения.
      acceptance: wiki/decision-self-employed-contractor.md с разбором по
      tax-boundaries.md этапам 2-3, шаблон договора и календарь мониторинга.
