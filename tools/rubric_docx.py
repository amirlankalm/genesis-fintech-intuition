"""Build docs/GRADING_CRITERIA.docx: the grading rubric of docs/GRADING_CRITERIA.md in English, Russian and Kazakh.

Run: uv run --with python-docx python tools/rubric_docx.py
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent.parent / "docs" / "GRADING_CRITERIA.docx"
FONT, MONO = "Arial", "Consolas"
NAVY, GREY, CODE = RGBColor(0x1F, 0x38, 0x64), RGBColor(0x59, 0x59, 0x59), RGBColor(0x9C, 0x27, 0x06)
HEAD_FILL, ZEBRA, BORDER = "1F3864", "F2F5FA", "BFC7D5"
STAGE_FILL = {"S": "E2F0D9", "B": "FFF2CC"}

# ── Shared structure: (category, points, [(id, stage, points)]) ─────────────────────────────
META = [
    ("A", 25, [("A1", "S", 3), ("A2", "S", 3), ("A3", "S", 3), ("A4", "S", 2), ("A5", "S", 3),
               ("A6", "S", 2), ("A7", "S", 3), ("A8", "S", 2), ("A9", "B", 4)]),
    ("B", 25, [("B1", "S", 2), ("B2", "S", 2), ("B3", "S", 2), ("B4", "S", 2), ("B5", "S", 1),
               ("B6", "B", 4), ("B7", "B", 6), ("B8", "B", 2), ("B9", "B", 2), ("B10", "B", 2)]),
    ("C", 25, [("C1", "S", 3), ("C2", "S", 5), ("C3", "S", 4), ("C4", "S", 4), ("C5", "S", 1),
               ("C6", "S", 1), ("C7", "S", 1), ("C8", "B", 4), ("C9", "B", 2)]),
    ("D", 15, [("D1", "S", 3), ("D2", "S", 2), ("D3", "S", 2), ("D4", "S", 1), ("D5", "B", 2),
               ("D6", "B", 3), ("D7", "B", 2)]),
]  # fmt: skip
SPLIT = {"A": (21, 4), "B": (9, 16), "C": (19, 6), "D": (8, 7), "E": (6, 4)}
FORMULA = "`F1 = 2TP/(2TP+FP+FN)`; `reward = clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1)`."

EN = {
    "lang": "English", "part": "Part 1",
    "title": "Grading criteria",
    "subtitle": "RL environment for financial-audit models trained on synthetic data",
    "intro": "**Internal verification rubric.** It evaluates our *environment*: generator, tools, hidden verifier and evaluation against the five categories and requirements of the Genesis Hackathon 2026 FinTech case [S1].",
    "terms_h": "Terms",
    "terms": [
        ("policy", "the model or script that acts in the environment."),
        ("truth", "the hidden list of real issues in an episode."),
        ("provenance", "the hidden record of how and where each error was injected."),
        ("seed", "the number an episode is generated from, deterministically."),
        ("episode", "one synthetic company with an audit task."),
        ("oracle", "a policy that knows the truth; an upper bound."),
        ("baseline", "a simple reference policy used for comparison."),
        ("submit", "the final action carrying the findings; it ends the episode."),
    ],
    "how_h": "How to use it",
    "how": [
        "Work from a fresh checkout. After dependencies are installed, turn the network off.",
        "Run the team's documented one-command check. If it fails, stop: see *Blockers*.",
        "For each criterion, find the named test, command or artifact and reproduce it yourself.",
        "In each category, make two spot attacks of your own, for example: repeat a correct finding, change its currency, cite an invented evidence id, send an action after submit.",
        "Fill in the score sheet. Write the command you used next to each score.",
        "Have someone other than the author do the grading. A score the author gives their own work is a self-assessment.",
    ],
    "score_h": "Scoring one criterion", "score_cols": ("Score", "When"),
    "score": [
        ("Full points", "You reproduced the evidence, and a test or command pins the behaviour."),
        ("Half points", "The behaviour is there, but no test pins it, or the evidence covers only part of the criterion."),
        ("Zero", "Absent, not reproducible, or only claimed. A claim without a command, artifact or measured result scores zero."),
    ],
    "stages_h": "Stages", "stages_intro": "Every criterion carries a stage tag.",
    "stages": [
        "**S (slice)** can be met by a generic engine and one vertical slice: one error family, one hand-verified episode and its clean twin. 63 points.",
        "**B (breadth)** needs the released case: a seeded generator, four families, interaction scenarios, shipped episodes. 37 points.",
    ],
    "stages_out": "Report two numbers: **Stage 1 = S points earned / 63** and **Full case = all points earned / 100**. A team is ready to start breadth when every blocker is clear and Stage 1 is at least 54 / 63 (85%).",
    "block_h": "Blockers", "block_intro": "No score is recorded until each of these is repaired [S1, section 7]:",
    "block": [
        "the policy can reach truth, provenance or a private seed by any path;",
        "the policy can write to the scorer or to evaluator files;",
        "any real company, person, bank, card or payment data is present;",
        "the core does not run from a fresh checkout.",
    ],
    "never": "**Never rewarded:** interface polish; model training without a controlled held-out comparison; difficulty that comes from contradictory or unsolvable data; a high oracle score by itself.",
    "cat": {"A": "Contract and isolation", "B": "Data and truth", "C": "Reward integrity",
            "D": "Reproducibility and generalization", "E": "Engineering and explanation"},
    "points": "points",
    "cols": ("ID", "Stage", "Pts", "Criterion", "Evidence to reproduce"),
    "e_intro": "Five criteria, each 0, 1 or 2 [S1]. Level 1 is reachable at stage S. Level 2 needs the whole case, except E2.",
    "e_cols": ("ID", "Criterion", "1 point", "2 points"),
    "sum_h": "Point summary", "sum_cols": ("Category", "S", "B", "Total"), "total": "Total",
    "sheet_h": "Score sheet", "sheet_cols": ("ID", "Available", "Earned", "Command or artifact used"),
    "sheet_fields": ("Team", "Grader", "Date", "Commit"),
    "stage1": "Stage 1 (S only)", "full": "Full case",
    "sheet_foot": "Blockers found: ________ .   Spot attacks tried: ________ .",
    "limits_h": "Limits of this rubric",
    "limits_intro": "An independent grader applied this rubric to its author's own repository and was asked to criticise the instrument. Its main points:",
    "limits": [
        "**The stage split fits one build plan.** Stage S describes what a generic engine and one slice can reach. Only 36% of “data and truth” is stage S, against 84% of “contract and isolation”. The 85% gate is the author's choice. **To compare teams, use the 100-point total and the blockers, not the stage score.**",
        "**Some criteria assume one design.** B1 expects recorded before and after values; D4 expects keyed id renaming; C3 pays for maximum matching even where a team forbids ambiguous truth outright, which is an equally sound answer. A3, A5, E3 and E4 fix tool names, caps, a file name and a baseline count taken from the draft case [S1]: check them against the case you were actually given.",
        "**Some criteria are easy.** A1, A6, C5, C6 and C7 are 8 points that any strict environment has. B5 can be met by a conversion helper that no scored path uses. E5 pays for listing limits and cannot tell whether the list is complete.",
        "**Not asked for, but worth noting:** evidence of learning signal (reward spread across policies, share of flat groups); more than one latent company before breadth; a spread of difficulty; throughput; an adapter for a real agent; uncertainty on the result sheet; proof that each check can fail; a threat model that names the reference backend; a rule for a tree that is not committed.",
        "**A passing probe is not the property.** Grade each property with an attack of your own, not with the team's own test.",
    ],
    "src_h": "Sources",
    "src": [
        "[S1] Genesis FinTech case specification: the five categories, their weights, the blockers and the behaviours listed under C4.",
        "Official Genesis Hackathon check definitions and evaluation criteria (20 November 2026).",
    ],
    "crit": {
        "A1": ("**Lifecycle contract.** `reset` returns task, manifest, policy summary and remaining budget. `step` returns observation, reward, terminated, truncated, info. Every value is JSON-serializable. Inspection reward is exactly 0.", "A scripted episode and a schema test."),
        "A2": ("**Budget and termination.** The step total includes the submit. A submit on the last allowed step is accepted. An inspection that exhausts the budget gives `truncated` with an empty final submission. A wall-time limit also truncates. The precedence rule is written down.", "Tests for the last-step submit, the exhausting inspection and the time limit."),
        "A3": ("**Narrow, bounded tools.** Only list, get record, get document, calculator and submit. Pages hold at most 50 rows and cursors are stable. An unknown id or action returns a bounded error and costs a step. No shell, SQL, filesystem or network tool.", "Tool tests; error messages come from a closed list."),
        "A4": ("**The calculator is a parser.** Decimal arithmetic only. Names, calls, attributes and imports are rejected. Length, nesting and magnitude are bounded.", "A test in which an injection attempt provably executes nothing."),
        "A5": ("**Malformed final versus invalid inspection.** A malformed final submission ends the episode at -1, and its validation error appears only in the evaluator log. An invalid inspection action costs a step and does not end the episode. The caps of 30 findings, 10 evidence ids and 1,000 characters are enforced.", "One test per branch and per cap."),
        "A6": ("**One submission, isolated resets.** Nothing is accepted after the end and the score cannot change. Each reset starts from fresh state.", "After-submit and after-truncation tests."),
        "A7": ("**Enforced truth boundary.** The policy runs outside the evaluator process and cannot read truth, provenance or seeds because of operating-system permissions, a sandbox or mounts. A module or package name is not a boundary. It also cannot kill, stall or exhaust the evaluator: a policy that never reads, never answers, floods, or leaves a child process behind ends in a defined way.", "A probe policy that tries and fails under confinement, and succeeds with confinement off. Hostile policies run under the real boundary. A written statement of what the containment does and does not protect."),
        "A8": ("**No leak through outputs or process metadata.** Observations, info, errors, exception text and policy-visible logs contain no truth, issue ids, private paths or seeds. Private ids do not encode the answer. The evaluator's command line carries no episode name or seed. Evaluation mode withholds reward and diagnostics until the run ends.", "A canary scan over everything a policy received; a probe that looks for a needle in the evaluator's arguments."),
        "A9": ("**Contract at case scale.** All of the above on 200 to 2,000-row episodes. Paging cost is measured. Every labelled issue is reachable within 100 steps through the real tools. Time and memory are measured at the largest size.", "Measured run at maximum size inside the stated envelope."),
        "B1": ("**Causal construction.** Latent history first, then derived clean records, then a typed mutation with before and after values recorded. Truth is computed from the resulting discrepancy, not copied from the mutation label and never asked of a language model.", "Builder code and provenance file; undoing the provenance gives the clean books."),
        "B2": ("**Accounting identities.** Declared identities are checked in code before and after injection. The check can fail. The documentation states that balanced books can still be wrong.", "Identity test with a corrupted ledger."),
        "B3": ("**Solvable from public evidence.** Each issue is decidable from records the tools return. Evidence sets cite only reachable ids. An episode whose truth needs an unpublished fact, or that no well-formed finding could match, is rejected at build or load. A policy that reads no truth solves it within the budget.", "Refusal tests; a truth-blind solver's measured score."),
        "B4": ("**Independent validation.** A checker that shares no code with the generator or verifier, ideally written by someone else, re-derives truth from public records. Each implemented family has a hand-calculated fixture. The checker is shown to fail on corrupted input.", "Checker run on good and corrupted episodes."),
        "B5": ("**Money and time semantics.** Integer minor units. Declared exponents, not assumed to be 2. Decimal-string rates with a stated direction. Declared rounding. Offsets on every timestamp. A period and timezone policy.", "Conversion tests with exponents 0 and 2."),
        "B6": ("**Seeded generator.** Consistent synthetic companies in the 200 to 2,000-row range from a seed and a config. No real data.", "Generated episodes pass the identity and independent checks."),
        "B7": ("**Four families.** Duplicate invoice; missing or partial allocation; FX rate or date mismatch; period cutoff. Each is independently configurable and has published amount, affected-id and evidence conventions, a hand-verified fixture and an independent check. 1.5 points each.", "One fixture and checker run per family."),
        "B8": ("**Clean cases and valid decoys.** Clean companies; split payments, refunds and legitimate repeats. Each decoy shares the suspicious surface feature of its error twin.", "Baselines on clean and decoy episodes."),
        "B9": ("**Interaction scenarios.** At least two. Overlapping rows are defined so that one discrepancy is not counted twice.", "Hand-verified interaction fixtures."),
        "B10": ("**Shortcut audit.** Error position, ids, filenames, currencies and templates carry no label. Nuisance features are counterbalanced. Random and flag-all baselines stay low.", "Shortcut tests and baseline results."),
        "C1": ("**Exact common reward.** " + FORMULA + " Both-empty gives F1 = 1. Undefined precision or recall is 0. The cost uses inspection steps only. Malformed is -1.", "A hand-computed table reproduced by tests."),
        "C2": ("**Strict true positives.** Type, affected ids, currency, amount tolerance and complete evidence are each individually necessary. No partial credit. One invented evidence id voids the finding.", "One failing case per condition."),
        "C3": ("**One-to-one maximum matching.** Repeats earn nothing and count as false positives. A case where greedy matching depends on order is tested. Counts are invariant under every permutation. Tie-breaking is published.", "Permutation and greedy-counterexample tests."),
        "C4": ("**Behaviours the case requires**, on the real environment: supported findings beat abstention on faulty books; abstention beats false alarms on clean books; a valid flag-all at the cap scores poorly; fewer inspections separate equal results only slightly. The lazy cases are measured and reported too: always-abstain, and a policy that never acts.", "Four environment-level tests; the lazy rows in the result sheet."),
        "C5": ("**Tolerance boundary.** Just inside passes, just outside fails, as declared.", "Boundary test."),
        "C6": ("**Prose is not scored.** The explanation never changes a score.", "Test with a persuasive wrong claim."),
        "C7": ("**Raw components kept.** TP, FP, FN, F1, the value before clipping, inspections and termination cause are in the evaluator report. An experimental reward, if any, is reported beside the common one, never instead of it.", "Evaluator report."),
        "C8": ("**Attack matrix per family.** The same attack tests pass for all four families and for the interaction scenarios.", "Per-family attack tests."),
        "C9": ("**Published semantics for every family.** Amount meaning, sign, tolerance and canonical affected ids for all four. Unresolved official rules are listed as questions, not presented as rules.", "Spec."),
        "D1": ("**Exact replay.** The same seed, config, version and actions give byte-identical records, transitions and rewards. A tampered log is detected. Digests are committed, so a second machine or Python version can be checked against them.", "Replay command; tamper test; committed digests reproduced elsewhere."),
        "D2": ("**Id and order invariance.** Consistent id renaming plus row shuffling preserves the oracle's findings, after renaming, and its reward. Truth derived again from the perturbed records equals the renamed truth. A real policy's F1 and step count are compared separately.", "Paired perturbation test."),
        "D3": ("**Determinism hygiene.** Local seeded randomness, no global generator. Canonical serialization. Stable ordering. Lockfile. Committed fixtures regenerate byte for byte.", "Regeneration test."),
        "D4": ("**No seed leakage.** The seed is absent from everything the policy sees. Episode ids and renamed ids cannot be inverted to the seed without an evaluator secret.", "Leak test."),
        "D5": ("**Reproducible generation.** The same seed and config give identical episodes on another machine and Python patch version.", "Cross-environment digest."),
        "D6": ("**Paired checks at scale.** 20 id and order pairs over generated episodes pass.", "Paired run."),
        "D7": ("**Split discipline.** 10 train and 10 dev episodes are shipped. Held-out seeds and configurations are separate. Related variants stay in one split.", "Episode manifests and split file."),
    },
    "e": [
        ("E1", "**One-command run**", "One command on a fresh checkout reproduces every number reported for the slice, offline.", "The same for the whole case, inside the stated envelope, with container instructions."),
        ("E2", "**Versioned configuration**", "Environment, schema and policy versions appear in manifests and logs.", "Plus a dependency lockfile and a license. Both points are stage S."),
        ("E3", "**Trajectory logs**", "`trajectories.jsonl` has episode id, step, action, observation, reward, terminated, truncated. The policy-visible view is separate from evaluator diagnostics.", "The same for all four baselines over the shipped episodes."),
        ("E4", "**Measured failure analysis**", "Four baseline policies measured on the same episodes. One failed trajectory traced to its earliest externally visible failure, with a patch and a regression test.", "A result sheet per family, with clean and interaction status, mean episode F1 and pooled F1."),
        ("E5", "**Honest limitations**", "States what is not built, what the containment does not protect, and which numbers are calculated rather than measured. Says what a memoriser would score. No training claim without a controlled comparison.", "Also covers the generator's limits and the open official questions."),
    ],
}  # fmt: skip

RU = {
    "lang": "Русский", "part": "Часть 2",
    "title": "Критерии оценки",
    "subtitle": "RL-среда для моделей финансового аудита, обучаемых на синтетических данных",
    "intro": "**Внутренняя рубрика верификации.** Она оценивает *среду* нашей команды: генератор, инструменты, скрытый верификатор и оценку по пяти категориям и требованиям кейса Genesis Hackathon 2026 FinTech [S1].",
    "terms_h": "Термины",
    "terms": [
        ("policy (политика)", "модель или скрипт, который действует в среде."),
        ("truth (истина)", "скрытый список настоящих проблем эпизода."),
        ("provenance", "скрытая запись того, как и где внесена каждая ошибка."),
        ("seed", "число, из которого эпизод генерируется детерминированно."),
        ("episode (эпизод)", "одна синтетическая компания с задачей аудита."),
        ("oracle (оракул)", "политика, которая знает истину; верхняя граница."),
        ("baseline (бейзлайн)", "простая эталонная политика для сравнения."),
        ("submit", "финальное действие с находками; завершает эпизод."),
    ],
    "how_h": "Как пользоваться",
    "how": [
        "Работайте с чистого клона репозитория. После установки зависимостей отключите сеть.",
        "Запустите задокументированную командой проверку одной командой. Если она падает, остановитесь: см. *Блокеры*.",
        "Для каждого критерия найдите названный тест, команду или артефакт и воспроизведите его сами.",
        "В каждой категории проведите две собственные выборочные атаки, например: повторите верную находку, смените её валюту, сошлитесь на выдуманный id доказательства, отправьте действие после submit.",
        "Заполните лист оценки. Рядом с каждой оценкой запишите использованную команду.",
        "Пусть оценивает не автор. Оценка, которую автор ставит своей работе, — это самооценка.",
    ],
    "score_h": "Оценка одного критерия", "score_cols": ("Оценка", "Когда"),
    "score": [
        ("Полный балл", "Вы воспроизвели доказательство, и тест или команда фиксирует поведение."),
        ("Половина балла", "Поведение есть, но его не фиксирует ни один тест, или доказательство покрывает лишь часть критерия."),
        ("Ноль", "Отсутствует, не воспроизводится или только заявлено. Заявление без команды, артефакта или измеренного результата получает ноль."),
    ],
    "stages_h": "Этапы", "stages_intro": "У каждого критерия есть метка этапа.",
    "stages": [
        "**S (срез)** достижим с общим движком и одним вертикальным срезом: одно семейство ошибок, один проверенный вручную эпизод и его чистый близнец. 63 балла.",
        "**B (охват)** требует выпущенного кейса: генератор с seed, четыре семейства, сценарии взаимодействия, поставляемые эпизоды. 37 баллов.",
    ],
    "stages_out": "Сообщайте два числа: **Этап 1 = набранные баллы S / 63** и **Полный кейс = все набранные баллы / 100**. Команда готова переходить к охвату, когда сняты все блокеры и Этап 1 не ниже 54 / 63 (85%).",
    "block_h": "Блокеры", "block_intro": "Никакая оценка не записывается, пока не исправлен каждый из пунктов [S1, раздел 7]:",
    "block": [
        "политика любым путём может добраться до истины, provenance или приватного seed;",
        "политика может писать в скорер или в файлы оценщика;",
        "присутствуют данные любой реальной компании, человека, банка, карты или платежа;",
        "ядро не запускается с чистого клона.",
    ],
    "never": "**Никогда не вознаграждается:** полировка интерфейса; обучение модели без контролируемого сравнения на отложенной выборке; сложность, возникающая из противоречивых или нерешаемых данных; высокий балл оракула сам по себе.",
    "cat": {"A": "Контракт и изоляция", "B": "Данные и истина", "C": "Целостность награды",
            "D": "Воспроизводимость и обобщение", "E": "Инженерия и объяснение"},
    "points": "баллов",
    "cols": ("ID", "Этап", "Баллы", "Критерий", "Что воспроизвести"),
    "e_intro": "Пять критериев, каждый 0, 1 или 2 балла [S1]. Уровень 1 достижим на этапе S. Уровень 2 требует полного кейса, кроме E2.",
    "e_cols": ("ID", "Критерий", "1 балл", "2 балла"),
    "sum_h": "Сводка баллов", "sum_cols": ("Категория", "S", "B", "Итого"), "total": "Итого",
    "sheet_h": "Лист оценки", "sheet_cols": ("ID", "Доступно", "Набрано", "Использованная команда или артефакт"),
    "sheet_fields": ("Команда", "Оценщик", "Дата", "Коммит"),
    "stage1": "Этап 1 (только S)", "full": "Полный кейс",
    "sheet_foot": "Найденные блокеры: ________ .   Проведённые выборочные атаки: ________ .",
    "limits_h": "Ограничения этой рубрики",
    "limits_intro": "Независимый оценщик применил рубрику к репозиторию её автора и по просьбе раскритиковал сам инструмент. Главное:",
    "limits": [
        "**Разбиение на этапы подогнано под один план работ.** Этап S описывает то, чего можно достичь общим движком и одним срезом. К этапу S относится только 36% категории «данные и истина» против 84% категории «контракт и изоляция». Порог 85% выбран автором. **Для сравнения команд используйте сумму из 100 баллов и блокеры, а не оценку этапа.**",
        "**Некоторые критерии предполагают один дизайн.** B1 ожидает записанные значения до и после; D4 — переименование id с ключом; C3 платит за максимальное паросочетание даже там, где команда вообще запрещает неоднозначную истину, что столь же обоснованно. A3, A5, E3 и E4 фиксируют имена инструментов, лимиты, имя файла и число бейзлайнов из черновика кейса [S1]: сверьте их с кейсом, который вы получили.",
        "**Некоторые критерии лёгкие.** A1, A6, C5, C6 и C7 — это 8 баллов, которые есть у любой строгой среды. B5 можно выполнить вспомогательной функцией конвертации, которую не использует ни один оцениваемый путь. E5 платит за перечисление ограничений и не может определить, полон ли список.",
        "**Не требуется, но стоит учесть:** признаки обучающего сигнала (разброс награды между политиками, доля плоских групп); больше одной латентной компании до этапа охвата; разброс сложности; пропускная способность; адаптер для реального агента; неопределённость в листе результатов; доказательство, что каждая проверка может провалиться; модель угроз с указанием эталонного бэкенда; правило для незакоммиченного дерева.",
        "**Пройденный зонд — ещё не свойство.** Оценивайте каждое свойство собственной атакой, а не тестом команды.",
    ],
    "src_h": "Источники",
    "src": [
        "[S1] Спецификация кейса Genesis FinTech: пять категорий, их веса, блокеры и поведение, перечисленное в C4.",
        "Официальные определения проверок и критерии оценки Genesis Hackathon (20 ноября 2026 г.).",
    ],
    "crit": {
        "A1": ("**Контракт жизненного цикла.** `reset` возвращает задачу, манифест, сводку политики и остаток бюджета. `step` возвращает observation, reward, terminated, truncated, info. Все значения сериализуемы в JSON. Награда за инспекцию равна ровно 0.", "Скриптовый эпизод и тест схемы."),
        "A2": ("**Бюджет и завершение.** Общее число шагов включает submit. Submit на последнем разрешённом шаге принимается. Инспекция, исчерпавшая бюджет, даёт `truncated` с пустой итоговой отправкой. Лимит реального времени тоже обрезает эпизод. Правило приоритета записано.", "Тесты на submit на последнем шаге, исчерпывающую инспекцию и лимит времени."),
        "A3": ("**Узкие ограниченные инструменты.** Только list, get record, get document, calculator и submit. Страница содержит не более 50 строк, курсоры стабильны. Неизвестный id или действие возвращает ограниченную ошибку и стоит шаг. Нет инструментов shell, SQL, файловой системы или сети.", "Тесты инструментов; сообщения об ошибках из закрытого списка."),
        "A4": ("**Калькулятор — это парсер.** Только десятичная арифметика. Имена, вызовы, атрибуты и импорты отклоняются. Длина, вложенность и величина ограничены.", "Тест, в котором попытка инъекции доказуемо ничего не выполняет."),
        "A5": ("**Некорректная итоговая отправка против невалидной инспекции.** Некорректная итоговая отправка завершает эпизод с -1, а её ошибка валидации видна только в журнале оценщика. Невалидное действие инспекции стоит шаг и не завершает эпизод. Лимиты 30 находок, 10 id доказательств и 1 000 символов соблюдаются.", "По тесту на каждую ветку и каждый лимит."),
        "A6": ("**Одна отправка, изолированные сбросы.** После окончания ничего не принимается, и оценка не может измениться. Каждый reset начинается с нового состояния.", "Тесты после submit и после обрезки."),
        "A7": ("**Принудительная граница истины.** Политика работает вне процесса оценщика и не может прочитать истину, provenance или seed благодаря правам ОС, песочнице или монтированию. Имя модуля или пакета — не граница. Она также не может убить, подвесить или исчерпать оценщика: политика, которая никогда не читает, не отвечает, флудит или оставляет дочерний процесс, завершается определённым образом.", "Политика-зонд, которая пытается и терпит неудачу под ограничением и преуспевает без него. Враждебные политики запускаются под реальной границей. Письменное описание того, что изоляция защищает и чего не защищает."),
        "A8": ("**Никаких утечек через вывод или метаданные процесса.** Observations, info, ошибки, текст исключений и видимые политике журналы не содержат истины, id проблем, приватных путей или seed. Приватные id не кодируют ответ. Командная строка оценщика не содержит имени эпизода или seed. Режим оценки скрывает награду и диагностику до конца прогона.", "Сканирование канареек по всему, что получила политика; зонд, ищущий «иголку» в аргументах оценщика."),
        "A9": ("**Контракт в масштабе кейса.** Всё перечисленное выше на эпизодах от 200 до 2 000 строк. Стоимость пагинации измерена. Каждая размеченная проблема достижима за 100 шагов через реальные инструменты. Время и память измерены на наибольшем размере.", "Измеренный прогон на максимальном размере внутри заявленных рамок."),
        "B1": ("**Причинное построение.** Сначала латентная история, затем выведенные из неё чистые записи, затем типизированная мутация с записанными значениями до и после. Истина вычисляется из получившегося расхождения, а не копируется из метки мутации и никогда не запрашивается у языковой модели.", "Код сборщика и файл provenance; отмена provenance возвращает чистые книги."),
        "B2": ("**Бухгалтерские тождества.** Заявленные тождества проверяются в коде до и после внесения ошибок. Проверка может провалиться. В документации сказано, что сбалансированные книги всё равно могут быть неверными.", "Тест тождеств с испорченным реестром."),
        "B3": ("**Решаемо по публичным данным.** Каждая проблема разрешима по записям, которые возвращают инструменты. Наборы доказательств ссылаются только на достижимые id. Эпизод, истина которого требует неопубликованного факта или которому не может соответствовать ни одна корректная находка, отклоняется при сборке или загрузке. Политика, не читающая истину, решает его в пределах бюджета.", "Тесты отказа; измеренный балл решателя, не видящего истину."),
        "B4": ("**Независимая проверка.** Чекер, не разделяющий кода с генератором или верификатором (в идеале написанный другим человеком), заново выводит истину из публичных записей. У каждого реализованного семейства есть фикстура, рассчитанная вручную. Показано, что чекер падает на испорченных входных данных.", "Прогон чекера на хороших и испорченных эпизодах."),
        "B5": ("**Семантика денег и времени.** Целые минорные единицы. Заявленные экспоненты, без допущения, что они равны 2. Курсы в виде десятичных строк с указанным направлением. Заявленное округление. Смещение часового пояса на каждой метке времени. Политика периода и часового пояса.", "Тесты конвертации с экспонентами 0 и 2."),
        "B6": ("**Генератор с seed.** Согласованные синтетические компании в диапазоне 200–2 000 строк из seed и конфигурации. Никаких реальных данных.", "Сгенерированные эпизоды проходят проверку тождеств и независимую проверку."),
        "B7": ("**Четыре семейства.** Дубликат счёта; отсутствующее или частичное распределение платежа; несоответствие курса или даты FX; отсечка периода. Каждое настраивается независимо и имеет опубликованные соглашения о сумме, затронутых id и доказательствах, проверенную вручную фикстуру и независимую проверку. По 1,5 балла.", "По одной фикстуре и прогону чекера на семейство."),
        "B8": ("**Чистые случаи и валидные ловушки.** Чистые компании; раздельные платежи, возвраты и законные повторы. Каждая ловушка разделяет подозрительный поверхностный признак со своим ошибочным близнецом.", "Бейзлайны на чистых эпизодах и эпизодах-ловушках."),
        "B9": ("**Сценарии взаимодействия.** Не менее двух. Пересекающиеся строки определены так, чтобы одно расхождение не учитывалось дважды.", "Проверенные вручную фикстуры взаимодействия."),
        "B10": ("**Аудит коротких путей.** Позиция ошибки, id, имена файлов, валюты и шаблоны не несут метки. Мешающие признаки сбалансированы. Случайный бейзлайн и «пометить всё» остаются низкими.", "Тесты коротких путей и результаты бейзлайнов."),
        "C1": ("**Точная общая награда.** " + FORMULA + " Если оба набора пусты, F1 = 1. Неопределённые precision или recall равны 0. Стоимость учитывает только шаги инспекции. Некорректная отправка = -1.", "Таблица, рассчитанная вручную и воспроизведённая тестами."),
        "C2": ("**Строгие истинно-положительные.** Тип, затронутые id, валюта, допуск по сумме и полный набор доказательств — каждое условие необходимо само по себе. Без частичного зачёта. Один выдуманный id доказательства аннулирует находку.", "По одному провальному случаю на каждое условие."),
        "C3": ("**Взаимно-однозначное максимальное паросочетание.** Повторы ничего не приносят и считаются ложноположительными. Протестирован случай, где жадное сопоставление зависит от порядка. Счётчики инвариантны относительно любой перестановки. Правило разрешения ничьих опубликовано.", "Тесты перестановок и контрпримера к жадному алгоритму."),
        "C4": ("**Поведение, которого требует кейс**, на реальной среде: обоснованные находки лучше воздержания на ошибочных книгах; воздержание лучше ложных тревог на чистых книгах; валидное «пометить всё» на лимите получает низкий балл; меньшее число инспекций лишь немного разделяет равные результаты. Ленивые случаи тоже измерены и показаны: «всегда воздерживаться» и политика, которая никогда не действует.", "Четыре теста на уровне среды; ленивые строки в листе результатов."),
        "C5": ("**Граница допуска.** Чуть внутри — проходит, чуть снаружи — нет, как заявлено.", "Граничный тест."),
        "C6": ("**Текст не оценивается.** Объяснение никогда не меняет оценку.", "Тест с убедительным неверным утверждением."),
        "C7": ("**Сырые компоненты сохраняются.** TP, FP, FN, F1, значение до обрезки, число инспекций и причина завершения есть в отчёте оценщика. Экспериментальная награда, если есть, показывается рядом с общей, но никогда вместо неё.", "Отчёт оценщика."),
        "C8": ("**Матрица атак по семействам.** Одни и те же тесты атак проходят для всех четырёх семейств и для сценариев взаимодействия.", "Тесты атак по семействам."),
        "C9": ("**Опубликованная семантика каждого семейства.** Смысл суммы, знак, допуск и канонические затронутые id для всех четырёх. Нерешённые официальные правила перечислены как вопросы, а не выданы за правила.", "Спецификация."),
        "D1": ("**Точное воспроизведение.** Те же seed, конфигурация, версия и действия дают побайтно идентичные записи, переходы и награды. Подделанный журнал обнаруживается. Дайджесты закоммичены, поэтому их можно проверить на второй машине или версии Python.", "Команда replay; тест подделки; закоммиченные дайджесты, воспроизведённые в другом месте."),
        "D2": ("**Инвариантность к id и порядку.** Согласованное переименование id вместе с перемешиванием строк сохраняет находки оракула (после переименования) и его награду. Истина, заново выведенная из изменённых записей, равна переименованной истине. F1 и число шагов реальной политики сравниваются отдельно.", "Парный тест возмущений."),
        "D3": ("**Гигиена детерминизма.** Локальная случайность с seed, без глобального генератора. Каноническая сериализация. Стабильный порядок. Lock-файл. Закоммиченные фикстуры регенерируются байт в байт.", "Тест регенерации."),
        "D4": ("**Нет утечки seed.** Seed отсутствует во всём, что видит политика. Id эпизодов и переименованные id нельзя обратить в seed без секрета оценщика.", "Тест утечки."),
        "D5": ("**Воспроизводимая генерация.** Те же seed и конфигурация дают идентичные эпизоды на другой машине и другой патч-версии Python.", "Дайджест, сверенный между средами."),
        "D6": ("**Парные проверки в масштабе.** Проходят 20 пар по id и порядку на сгенерированных эпизодах.", "Парный прогон."),
        "D7": ("**Дисциплина разбиения.** Поставляются 10 train- и 10 dev-эпизодов. Отложенные seed и конфигурации отделены. Связанные варианты остаются в одном разбиении.", "Манифесты эпизодов и файл разбиения."),
    },
    "e": [
        ("E1", "**Запуск одной командой**", "Одна команда на чистом клоне офлайн воспроизводит каждое число, заявленное для среза.", "То же для всего кейса, в заявленных рамках, с инструкциями для контейнера."),
        ("E2", "**Версионированная конфигурация**", "Версии среды, схемы и политики есть в манифестах и журналах.", "Плюс lock-файл зависимостей и лицензия. Оба балла — этап S."),
        ("E3", "**Журналы траекторий**", "`trajectories.jsonl` содержит id эпизода, шаг, действие, observation, reward, terminated, truncated. Видимое политике представление отделено от диагностики оценщика.", "То же для всех четырёх бейзлайнов на поставляемых эпизодах."),
        ("E4", "**Измеренный анализ сбоев**", "Четыре бейзлайн-политики измерены на одних и тех же эпизодах. Одна провальная траектория прослежена до самого раннего внешне видимого сбоя, с патчем и регрессионным тестом.", "Лист результатов по каждому семейству: статус чистых случаев и взаимодействий, средний F1 по эпизодам и объединённый F1."),
        ("E5", "**Честные ограничения**", "Указано, что не построено, от чего не защищает изоляция и какие числа рассчитаны, а не измерены. Сказано, сколько набрал бы «запоминатель». Никаких заявлений об обучении без контролируемого сравнения.", "Также охватывает ограничения генератора и открытые официальные вопросы."),
    ],
}  # fmt: skip

KK = {
    "lang": "Қазақша", "part": "3-бөлім",
    "title": "Бағалау критерийлері",
    "subtitle": "Синтетикалық деректерде оқытылатын қаржылық аудит модельдеріне арналған RL-орта",
    "intro": "**Ішкі тексеру рубрикасы.** Ол командамыздың *ортасын* бағалайды: генератор, құралдар, жасырын верификатор және Genesis Hackathon 2026 FinTech [S1] талаптарына сәйкес бағалау.",
    "terms_h": "Терминдер",
    "terms": [
        ("policy (саясат)", "ортада әрекет ететін модель немесе скрипт."),
        ("truth (ақиқат)", "эпизодтағы нақты мәселелердің жасырын тізімі."),
        ("provenance", "әр қатенің қалай және қайда енгізілгені туралы жасырын жазба."),
        ("seed", "эпизод детерминистік түрде генерацияланатын сан."),
        ("episode (эпизод)", "аудит тапсырмасы бар бір синтетикалық компания."),
        ("oracle (оракул)", "ақиқатты білетін саясат; жоғарғы шек."),
        ("baseline (бейзлайн)", "салыстыруға арналған қарапайым эталондық саясат."),
        ("submit", "табылымдары бар соңғы әрекет; эпизодты аяқтайды."),
    ],
    "how_h": "Қалай қолдану керек",
    "how": [
        "Репозиторийдің таза клонынан жұмыс істеңіз. Тәуелділіктерді орнатқаннан кейін желіні өшіріңіз.",
        "Команданың құжатталған бір командалық тексерісін іске қосыңыз. Ол сәтсіз болса, тоқтаңыз: *Блокерлер* бөлімін қараңыз.",
        "Әр критерий үшін аталған тестті, команданы немесе артефактіні тауып, оны өзіңіз қайталаңыз.",
        "Әр санатта өзіңіздің екі іріктемелі шабуылыңызды жасаңыз, мысалы: дұрыс табылымды қайталаңыз, оның валютасын өзгертіңіз, ойдан шығарылған дәлел id-іне сілтеме жасаңыз, submit-тен кейін әрекет жіберіңіз.",
        "Бағалау парағын толтырыңыз. Әр бағаның жанына қолданған командаңызды жазыңыз.",
        "Бағалауды автор емес адам жүргізсін. Автордың өз жұмысына қойған бағасы — өзін-өзі бағалау.",
    ],
    "score_h": "Бір критерийді бағалау", "score_cols": ("Баға", "Қашан"),
    "score": [
        ("Толық балл", "Дәлелді өзіңіз қайталадыңыз және мінез-құлықты тест немесе команда бекітеді."),
        ("Жарты балл", "Мінез-құлық бар, бірақ оны ешбір тест бекітпейді немесе дәлел критерийдің бір бөлігін ғана қамтиды."),
        ("Нөл", "Жоқ, қайталанбайды немесе тек мәлімделген. Командасы, артефактісі немесе өлшенген нәтижесі жоқ мәлімдеме нөл алады."),
    ],
    "stages_h": "Кезеңдер", "stages_intro": "Әр критерийдің кезең белгісі бар.",
    "stages": [
        "**S (кесінді)** жалпы қозғалтқыш пен бір тік кесінді арқылы орындалады: бір қате тобы, қолмен тексерілген бір эпизод және оның таза егізі. 63 балл.",
        "**B (ауқым)** жарияланған кейсті қажет етеді: seed бойынша генератор, төрт топ, өзара әсер сценарийлері, жеткізілетін эпизодтар. 37 балл.",
    ],
    "stages_out": "Екі сан көрсетіңіз: **1-кезең = жинаған S балдары / 63** және **Толық кейс = барлық жинаған балдар / 100**. Барлық блокерлер жойылып, 1-кезең кемінде 54 / 63 (85%) болғанда, команда ауқымға кірісуге дайын.",
    "block_h": "Блокерлер", "block_intro": "Төмендегілердің әрқайсысы түзетілмейінше ешбір баға жазылмайды [S1, 7-бөлім]:",
    "block": [
        "саясат кез келген жолмен ақиқатқа, provenance-қа немесе жеке seed-ке жете алады;",
        "саясат скорерге немесе бағалаушы файлдарына жаза алады;",
        "кез келген нақты компанияның, адамның, банктің, картаның немесе төлемнің деректері бар;",
        "ядро таза клоннан іске қосылмайды.",
    ],
    "never": "**Ешқашан марапатталмайды:** интерфейсті әрлеу; бақыланатын holdout салыстыруынсыз модельді оқыту; қайшылықты немесе шешілмейтін деректерден туындайтын күрделілік; оракулдың жоғары балы өз алдына.",
    "cat": {"A": "Келісімшарт және оқшаулау", "B": "Деректер және ақиқат", "C": "Марапаттың тұтастығы",
            "D": "Қайталанушылық және жалпылау", "E": "Инженерия және түсіндіру"},
    "points": "балл",
    "cols": ("ID", "Кезең", "Балл", "Критерий", "Қайталанатын дәлел"),
    "e_intro": "Бес критерий, әрқайсысы 0, 1 немесе 2 балл [S1]. 1-деңгейге S кезеңінде жетуге болады. 2-деңгей E2-ден басқасында толық кейсті қажет етеді.",
    "e_cols": ("ID", "Критерий", "1 балл", "2 балл"),
    "sum_h": "Балдар жиынтығы", "sum_cols": ("Санат", "S", "B", "Барлығы"), "total": "Барлығы",
    "sheet_h": "Бағалау парағы", "sheet_cols": ("ID", "Қолжетімді", "Жиналды", "Қолданылған команда немесе артефакт"),
    "sheet_fields": ("Команда", "Бағалаушы", "Күні", "Коммит"),
    "stage1": "1-кезең (тек S)", "full": "Толық кейс",
    "sheet_foot": "Табылған блокерлер: ________ .   Жасалған іріктемелі шабуылдар: ________ .",
    "limits_h": "Осы рубриканың шектеулері",
    "limits_intro": "Тәуелсіз бағалаушы рубриканы оның авторының репозиторийіне қолданып, сұраныс бойынша құралдың өзін сынады. Негізгі ойлар:",
    "limits": [
        "**Кезеңдерге бөлу бір жұмыс жоспарына бейімделген.** S кезеңі жалпы қозғалтқыш пен бір кесінді жете алатын нәрсені сипаттайды. «Деректер және ақиқат» санатының тек 36%-ы S кезеңіне жатады, ал «келісімшарт және оқшаулау» санатында бұл 84%. 85% шегін автор таңдаған. **Командаларды салыстыру үшін кезең бағасын емес, 100 балдық жиынтықты және блокерлерді қолданыңыз.**",
        "**Кейбір критерийлер бір дизайнды болжайды.** B1 жазылған «дейін» және «кейін» мәндерін күтеді; D4 кілтпен id қайта атауды күтеді; C3 команда екіұшты ақиқатқа мүлдем тыйым салған жағдайда да максималды сәйкестендіру үшін балл береді, ал бұл да дәл сондай негізді шешім. A3, A5, E3 және E4 кейс жобасынан [S1] алынған құрал атауларын, шектерді, файл атауын және бейзлайн санын бекітеді: оларды өзіңізге берілген кейспен салыстырыңыз.",
        "**Кейбір критерийлер жеңіл.** A1, A6, C5, C6 және C7 — кез келген қатаң ортада бар 8 балл. B5-ті ешбір бағаланатын жол қолданбайтын көмекші айырбастау функциясы арқылы орындауға болады. E5 шектеулерді тізгені үшін балл береді, бірақ тізімнің толық екенін ажырата алмайды.",
        "**Талап етілмейді, бірақ ескерген жөн:** оқыту сигналының дәлелі (саясаттар арасындағы марапат шашырауы, жалпақ топтардың үлесі); ауқымға дейін бірден көп жасырын компания; күрделілік шашырауы; өткізу қабілеті; нақты агентке арналған адаптер; нәтижелер парағындағы белгісіздік; әр тексерістің сәтсіз бола алатынының дәлелі; эталондық бэкендті атайтын қауіп моделі; коммиттелмеген ағашқа арналған ереже.",
        "**Өткен зонд — әлі қасиет емес.** Әр қасиетті команданың өз тестімен емес, өзіңіздің шабуылыңызбен бағалаңыз.",
    ],
    "src_h": "Дереккөздер",
    "src": [
        "[S1] Genesis FinTech тапсырма спецификациясы: бес санат, олардың салмақтары, блокерлер және C4-те аталған мінез-құлықтар.",
        "Genesis Hackathon ресми тексеру анықтамалары мен бағалау критерийлері (2026 жылғы 20 қараша).",
    ],
    "crit": {
        "A1": ("**Өмірлік цикл келісімшарты.** `reset` тапсырманы, манифестті, саясат қорытындысын және қалған бюджетті қайтарады. `step` observation, reward, terminated, truncated, info қайтарады. Барлық мәндер JSON-ға сериализацияланады. Тексеру (inspection) марапаты дәл 0.", "Сценарийлік эпизод және схема тесті."),
        "A2": ("**Бюджет және аяқталу.** Қадамдардың жалпы саны submit-ті қамтиды. Соңғы рұқсат етілген қадамдағы submit қабылданады. Бюджетті таусатын тексеру бос соңғы жіберіліммен `truncated` береді. Нақты уақыт шегі де эпизодты үзеді. Басымдық ережесі жазылған.", "Соңғы қадамдағы submit, бюджетті таусатын тексеру және уақыт шегі тестілері."),
        "A3": ("**Тар, шектелген құралдар.** Тек list, get record, get document, calculator және submit. Бетте ең көбі 50 жол, курсорлар тұрақты. Белгісіз id немесе әрекет шектелген қате қайтарады және бір қадам тұрады. Shell, SQL, файлдық жүйе немесе желі құралдары жоқ.", "Құрал тестілері; қате хабарлары жабық тізімнен алынады."),
        "A4": ("**Калькулятор — талдағыш (parser).** Тек ондық арифметика. Атаулар, шақырулар, атрибуттар және импорттар қабылданбайды. Ұзындық, ендіру тереңдігі және шама шектелген.", "Инъекция әрекеті ештеңе орындамайтыны дәлелденетін тест."),
        "A5": ("**Қате пішімделген соңғы жіберілім мен жарамсыз тексеру.** Қате пішімделген соңғы жіберілім эпизодты -1 мәнімен аяқтайды, ал оның валидация қатесі тек бағалаушы журналында көрінеді. Жарамсыз тексеру әрекеті бір қадам тұрады және эпизодты аяқтамайды. 30 табылым, 10 дәлел id-і және 1 000 таңба шектері сақталады.", "Әр тармаққа және әр шекке бір тест."),
        "A6": ("**Бір жіберілім, оқшауланған reset-тер.** Аяқталғаннан кейін ештеңе қабылданбайды және баға өзгермейді. Әр reset жаңа күйден басталады.", "Submit-тен кейінгі және үзілуден кейінгі тестілер."),
        "A7": ("**Мәжбүрлі ақиқат шекарасы.** Саясат бағалаушы процесінен тыс жұмыс істейді және ОЖ рұқсаттары, құмсалғыш (sandbox) немесе mount арқасында ақиқатты, provenance-ты немесе seed-терді оқи алмайды. Модуль немесе пакет атауы шекара емес. Ол сондай-ақ бағалаушыны өлтіре, тоқтатып қоя немесе ресурсын таусата алмайды: ешқашан оқымайтын, жауап бермейтін, тасқын жіберетін немесе еншілес процесс қалдыратын саясат белгіленген жолмен аяқталады.", "Шектеу кезінде әрекет етіп сәтсіз болатын, ал шектеусіз сәтті болатын зонд-саясат. Қаскөй саясаттар нақты шекара астында іске қосылады. Оқшаулау нені қорғайтыны және нені қорғамайтыны туралы жазбаша мәлімдеме."),
        "A8": ("**Шығыс немесе процесс метадеректері арқылы ағып кету жоқ.** Observations, info, қателер, ерекше жағдай мәтіндері және саясатқа көрінетін журналдарда ақиқат, мәселе id-лері, жеке жолдар немесе seed-тер жоқ. Жеке id-лер жауапты кодтамайды. Бағалаушының командалық жолында эпизод атауы немесе seed жоқ. Бағалау режимі марапат пен диагностиканы іске қосу аяқталғанша жасырады.", "Саясат алған барлық нәрсе бойынша канарейка сканері; бағалаушы аргументтерінен «инені» іздейтін зонд."),
        "A9": ("**Кейс ауқымындағы келісімшарт.** Жоғарыдағылардың бәрі 200–2 000 жолдық эпизодтарда. Беттеу құны өлшенген. Әр белгіленген мәселеге нақты құралдар арқылы 100 қадам ішінде жетуге болады. Ең үлкен өлшемде уақыт пен жад өлшенген.", "Мәлімделген шектер ішіндегі ең үлкен өлшемде өлшенген іске қосу."),
        "B1": ("**Себептік құрылым.** Алдымен жасырын тарих, содан кейін одан шығарылған таза жазбалар, содан кейін «дейін» және «кейін» мәндері жазылған типтелген мутация. Ақиқат мутация белгісінен көшірілмейді және ешқашан тілдік модельден сұралмайды: ол пайда болған сәйкессіздіктен есептеледі.", "Құрастырушы коды және provenance файлы; provenance-ты кері қайтару таза кітаптарды береді."),
        "B2": ("**Бухгалтерлік тепе-теңдіктер.** Мәлімделген тепе-теңдіктер қате енгізуге дейін және кейін кодта тексеріледі. Тексеріс сәтсіз бола алады. Құжаттамада теңестірілген кітаптардың да қате болуы мүмкін екені айтылған.", "Бүлінген тізілімі бар тепе-теңдік тесті."),
        "B3": ("**Ашық дәлелдер бойынша шешіледі.** Әр мәселені құралдар қайтаратын жазбалар бойынша шешуге болады. Дәлел жиындары тек қолжетімді id-лерге сілтейді. Ақиқаты жарияланбаған фактіні қажет ететін немесе ешбір дұрыс табылым сәйкес келмейтін эпизод құрастыру не жүктеу кезінде қабылданбайды. Ақиқатты оқымайтын саясат оны бюджет ішінде шешеді.", "Бас тарту тестілері; ақиқатты көрмейтін шешушінің өлшенген балы."),
        "B4": ("**Тәуелсіз тексеру.** Генератормен немесе верификатормен ортақ коды жоқ (ең дұрысы, басқа адам жазған) тексеруші ақиқатты ашық жазбалардан қайта шығарады. Әр іске асырылған топтың қолмен есептелген фикстурасы бар. Тексерушінің бүлінген кірісте сәтсіз болатыны көрсетілген.", "Тексерушіні жақсы және бүлінген эпизодтарда іске қосу."),
        "B5": ("**Ақша мен уақыт семантикасы.** Бүтін кіші бірліктер (minor units). Мәлімделген экспоненттер, 2 деп болжанбайды. Бағыты көрсетілген ондық жол түріндегі бағамдар. Мәлімделген дөңгелектеу. Әр уақыт белгісінде уақыт белдеуінің ығысуы (offset). Кезең және уақыт белдеуі саясаты.", "0 және 2 экспоненттерімен айырбастау тестілері."),
        "B6": ("**Seed бойынша генератор.** Seed пен конфигурациядан 200–2 000 жол аралығындағы үйлесімді синтетикалық компаниялар. Нақты деректер жоқ.", "Генерацияланған эпизодтар тепе-теңдік және тәуелсіз тексерістерден өтеді."),
        "B7": ("**Төрт топ.** Шот-фактураның көшірмесі; төлемнің жоқ немесе ішінара бөлінуі; FX бағамы немесе күнінің сәйкессіздігі; кезеңді кесу (cutoff). Әрқайсысы тәуелсіз бапталады және сома, әсер еткен id-лер мен дәлелдер бойынша жарияланған келісімдері, қолмен тексерілген фикстурасы және тәуелсіз тексерісі бар. Әрқайсысы 1,5 балл.", "Әр топқа бір фикстура және тексерушіні іске қосу."),
        "B8": ("**Таза жағдайлар және жарамды алдағыштар.** Таза компаниялар; бөлінген төлемдер, қайтарымдар және заңды қайталаулар. Әр алдағыш өзінің қателі егізімен бірдей күдікті сыртқы белгіге ие.", "Таза және алдағыш эпизодтардағы бейзлайндар."),
        "B9": ("**Өзара әсер сценарийлері.** Кемінде екеу. Бір сәйкессіздік екі рет есептелмейтіндей етіп қиылысатын жолдар анықталған.", "Қолмен тексерілген өзара әсер фикстуралары."),
        "B10": ("**Төте жолдар аудиті.** Қатенің орны, id-лер, файл атаулары, валюталар және үлгілер белгіні тасымалдамайды. Кедергі белгілер теңгерілген. Кездейсоқ және «бәрін белгілеу» бейзлайндары төмен күйде қалады.", "Төте жол тестілері және бейзлайн нәтижелері."),
        "C1": ("**Дәл ортақ марапат.** " + FORMULA + " Екі жиын да бос болса, F1 = 1. Анықталмаған precision немесе recall 0-ге тең. Құн тек тексеру қадамдарын ескереді. Қате пішімделген жіберілім = -1.", "Қолмен есептелген, тестілер қайталайтын кесте."),
        "C2": ("**Қатаң шын-оң нәтижелер.** Түрі, әсер еткен id-лер, валюта, сома төзімділігі және толық дәлел — әрқайсысы жеке-жеке қажет. Ішінара есептеу жоқ. Бір ойдан шығарылған дәлел id-і табылымды жарамсыз етеді.", "Әр шартқа бір сәтсіз жағдай."),
        "C3": ("**Бірге-бір максималды сәйкестендіру.** Қайталаулар ештеңе бермейді және жалған-оң болып саналады. Ашкөз (greedy) сәйкестендіру ретке тәуелді болатын жағдай тестіленген. Есептер кез келген алмастыруда өзгермейді. Тең жағдайды шешу ережесі жарияланған.", "Алмастыру тестілері және ашкөз алгоритмге қарсы мысал тестілері."),
        "C4": ("**Кейс талап ететін мінез-құлықтар**, нақты ортада: қателі кітаптарда негізделген табылымдар қалыс қалудан жақсы; таза кітаптарда қалыс қалу жалған дабылдан жақсы; шектегі жарамды «бәрін белгілеу» төмен балл алады; аз тексеру тең нәтижелерді тек аздап ажыратады. Жалқау жағдайлар да өлшеніп, көрсетіледі: «әрқашан қалыс қалу» және ешқашан әрекет етпейтін саясат.", "Орта деңгейіндегі төрт тест; нәтижелер парағындағы жалқау жолдар."),
        "C5": ("**Төзімділік шекарасы.** Сәл ішінде — өтеді, сәл сыртында — өтпейді, мәлімделгендей.", "Шекаралық тест."),
        "C6": ("**Мәтін бағаланбайды.** Түсіндірме ешқашан бағаны өзгертпейді.", "Сенімді, бірақ қате мәлімдемесі бар тест."),
        "C7": ("**Шикі құрамдас бөліктер сақталады.** TP, FP, FN, F1, кесуге дейінгі мән, тексерулер саны және аяқталу себебі бағалаушы есебінде бар. Эксперименттік марапат болса, ол ортақ марапаттың орнына емес, жанында көрсетіледі.", "Бағалаушы есебі."),
        "C8": ("**Әр топқа шабуыл матрицасы.** Бірдей шабуыл тестілері төрт топтың бәрінде және өзара әсер сценарийлерінде өтеді.", "Әр топқа шабуыл тестілері."),
        "C9": ("**Әр топтың жарияланған семантикасы.** Төртеуі үшін соманың мағынасы, таңбасы, төзімділік және канондық әсер еткен id-лер. Шешілмеген ресми ережелер ереже ретінде емес, сұрақ ретінде тізілген.", "Спецификация."),
        "D1": ("**Дәл қайталау.** Бірдей seed, конфигурация, нұсқа және әрекеттер байт-байтқа бірдей жазбаларды, ауысуларды және марапаттарды береді. Жалғанған журнал анықталады. Дайджесттер коммиттелген, сондықтан оларды екінші машинада немесе Python нұсқасында тексеруге болады.", "Replay командасы; жалғандық тесті; басқа жерде қайталанған коммиттелген дайджесттер."),
        "D2": ("**Id мен ретке инварианттық.** Id-лерді үйлесімді қайта атау және жолдарды араластыру оракулдың табылымдарын (қайта атаудан кейін) және оның марапатын сақтайды. Өзгертілген жазбалардан қайта шығарылған ақиқат қайта аталған ақиқатқа тең. Нақты саясаттың F1-і мен қадам саны бөлек салыстырылады.", "Жұптық өзгерту тесті."),
        "D3": ("**Детерминизм гигиенасы.** Жергілікті seed-тік кездейсоқтық, ғаламдық генератор жоқ. Канондық сериализация. Тұрақты рет. Lock-файл. Коммиттелген фикстуралар байт-байтқа қайта генерацияланады.", "Қайта генерациялау тесті."),
        "D4": ("**Seed ағып кетпейді.** Seed саясат көретін ешнәрседе жоқ. Эпизод id-лерін және қайта аталған id-лерді бағалаушы құпиясынсыз seed-ке кері айналдыру мүмкін емес.", "Ағып кету тесті."),
        "D5": ("**Қайталанатын генерация.** Бірдей seed пен конфигурация басқа машинада және Python-ның басқа патч нұсқасында бірдей эпизодтар береді.", "Орталар арасында салыстырылған дайджест."),
        "D6": ("**Ауқымдағы жұптық тексерістер.** Генерацияланған эпизодтардағы id және рет бойынша 20 жұп өтеді.", "Жұптық іске қосу."),
        "D7": ("**Бөлу тәртібі.** 10 train және 10 dev эпизод жеткізіледі. Holdout seed-тер мен конфигурациялар бөлек. Байланысты нұсқалар бір бөлікте қалады.", "Эпизод манифесттері және бөлу файлы."),
    },
    "e": [
        ("E1", "**Бір командамен іске қосу**", "Таза клондағы бір команда кесінді үшін көрсетілген әр санды офлайн қайталайды.", "Толық кейс үшін де солай, мәлімделген шектер ішінде, контейнер нұсқауларымен."),
        ("E2", "**Нұсқаланған конфигурация**", "Орта, схема және саясат нұсқалары манифесттер мен журналдарда бар.", "Сонымен қатар тәуелділіктердің lock-файлы және лицензия. Екі балл да S кезеңі."),
        ("E3", "**Траектория журналдары**", "`trajectories.jsonl` ішінде эпизод id-і, қадам, әрекет, observation, reward, terminated, truncated бар. Саясатқа көрінетін көрініс бағалаушы диагностикасынан бөлек.", "Жеткізілетін эпизодтардағы төрт бейзлайнның бәрі үшін де солай."),
        ("E4", "**Өлшенген сәтсіздік талдауы**", "Төрт бейзлайн саясаты бірдей эпизодтарда өлшенген. Бір сәтсіз траектория сырттай көрінетін ең ерте сәтсіздікке дейін қадағаланып, патчпен және регрессия тестімен берілген.", "Әр топқа арналған нәтижелер парағы: таза және өзара әсер күйі, эпизод бойынша орташа F1 және жиынтық F1."),
        ("E5", "**Адал шектеулер**", "Не салынбағаны, оқшаулау нені қорғамайтыны және қай сандар өлшенбей, есептелгені айтылған. Жаттап алушы (memoriser) қанша балл алатыны айтылған. Бақыланатын салыстырусыз оқыту туралы мәлімдеме жоқ.", "Сонымен қатар генератордың шектеулері мен ашық ресми сұрақтарды қамтиды."),
    ],
}  # fmt: skip

LANGS = (EN, RU, KK)


# ── Low-level formatting helpers ─────────────────────────────────────────────────────────────
def _font(
    run, size: float | None = None, bold: bool | None = None, color: RGBColor | None = None, mono: bool = False
) -> None:
    name = MONO if mono else FONT
    run.font.name = name
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for key in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(key), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


TOKENS = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)")


def rich(par, text: str, size: float = 10, color: RGBColor | None = None, bold: bool = False) -> None:
    """Write text with **bold**, *italic* and `code` spans."""
    for piece in TOKENS.split(text):
        if not piece:
            continue
        if piece.startswith("**"):
            _font(par.add_run(piece[2:-2]), size, True, color)
        elif piece.startswith("`"):
            _font(par.add_run(piece[1:-1]), size - 0.5, bold, CODE, mono=True)
        elif piece.startswith("*"):
            run = par.add_run(piece[1:-1])
            _font(run, size, bold, color)
            run.font.italic = True
        else:
            _font(par.add_run(piece), size, bold, color)


def para(
    doc,
    text: str = "",
    size: float = 10,
    after: float = 6,
    color: RGBColor | None = None,
    style: str | None = None,
    align=None,
):
    par = doc.add_paragraph(style=style)
    par.paragraph_format.space_after = Pt(after)
    if align is not None:
        par.alignment = align
    if text:
        rich(par, text, size, color)
    return par


def heading(doc, text: str, level: int) -> None:
    par = doc.add_heading(level=level)
    par.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    par.paragraph_format.space_after = Pt(6)
    par.paragraph_format.keep_with_next = True
    _font(par.add_run(text), {1: 18, 2: 13, 3: 11}[level], True, NAVY)


def shade(cell, fill: str) -> None:
    props = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def _borders(table) -> None:
    props = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:color"), BORDER)
        borders.append(node)
    props.append(borders)


def _row_flags(row, header: bool) -> None:
    props = row._tr.get_or_add_trPr()
    props.append(OxmlElement("w:cantSplit"))
    if header:
        props.append(OxmlElement("w:tblHeader"))


def table(doc, cols, rows, widths, center=(), stage_col: int | None = None, bold_last: bool = False, size: float = 9):
    tbl = doc.add_table(rows=1, cols=len(cols))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    _borders(tbl)
    _row_flags(tbl.rows[0], header=True)
    for i, (cell, title) in enumerate(zip(tbl.rows[0].cells, cols, strict=True)):
        shade(cell, HEAD_FILL)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        par = cell.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER if i in center else WD_ALIGN_PARAGRAPH.LEFT
        _font(par.add_run(title), size, True, RGBColor(0xFF, 0xFF, 0xFF))
    for r, values in enumerate(rows):
        row = tbl.add_row()
        _row_flags(row, header=False)
        last = bold_last and r == len(rows) - 1
        for i, (cell, value) in enumerate(zip(row.cells, values, strict=True)):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            if stage_col == i and value in STAGE_FILL:
                shade(cell, STAGE_FILL[value])
            elif r % 2 == 1 or last:
                shade(cell, "DCE3EF" if last else ZEBRA)
            par = cell.paragraphs[0]
            par.paragraph_format.space_after = Pt(0)
            if i in center:
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            rich(par, str(value), size, bold=last or (i == 0 and len(str(value)) <= 4))
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl._tbl.tblPr.append(layout)
    for col, width in zip(tbl._tbl.tblGrid.findall(qn("w:gridCol")), widths, strict=True):
        col.set(qn("w:w"), str(int(Cm(width).twips)))
    for row in tbl.rows:
        for cell, width in zip(row.cells, widths, strict=True):
            cell.width = Cm(width)
    para(doc, after=4)
    return tbl


def page_break(doc) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _field(par, instruction: str) -> None:
    for kind, text in (("begin", None), (None, instruction), ("separate", None), (None, "1"), ("end", None)):
        run = par.add_run()
        _font(run, 8, color=GREY)
        if kind:
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), kind)
        elif text == instruction:
            node = OxmlElement("w:instrText")
            node.set(qn("xml:space"), "preserve")
            node.text = f" {instruction} "
        else:
            node = OxmlElement("w:t")
            node.text = text
        run._r.append(node)


# ── Document ─────────────────────────────────────────────────────────────────────────────────
def setup(doc) -> None:
    section = doc.sections[0]
    section.page_height, section.page_width = Cm(29.7), Cm(21.0)
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.8)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = FONT, Pt(10)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    head = section.header.paragraphs[0]
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _font(head.add_run("Genesis FinTech · Grading criteria · Критерии оценки · Бағалау критерийлері"), 8, color=GREY)
    foot = section.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(foot.add_run("Unofficial rubric · v1.0 · "), 8, color=GREY)
    _field(foot, "PAGE")
    _font(foot.add_run(" / "), 8, color=GREY)
    _field(foot, "NUMPAGES")


def cover(doc) -> None:
    for _ in range(5):
        para(doc, after=12)
    for lang in LANGS:
        par = para(doc, after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
        _font(par.add_run(lang["title"]), 26, True, NAVY)
    para(doc, after=18)
    for lang in LANGS:
        para(doc, lang["subtitle"], 11, 3, GREY, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, after=24)
    par = para(doc, after=4, align=WD_ALIGN_PARAGRAPH.CENTER)
    _font(par.add_run("Genesis hackathon · FinTech case"), 12, True)
    para(doc, "Unofficial rubric · version 1.0 · 18 November 2026", 10, 30, GREY, align=WD_ALIGN_PARAGRAPH.CENTER)
    table(doc, ("", "Language", "Contents"),
          [(lang["part"], lang["lang"], " · ".join((lang["how_h"], lang["block_h"], "A–E", lang["sheet_h"])))
           for lang in LANGS], (2.6, 3.0, 11.4))  # fmt: skip
    para(doc, after=18)
    para(doc, "Five categories, 100 points: A 25 · B 25 · C 25 · D 15 · E 10. Every criterion is tagged S (slice, 63 points) "
              "or B (breadth, 37 points). Free to use and adapt for judging or self-review. Not the official judging.",
         9, 0, GREY, align=WD_ALIGN_PARAGRAPH.CENTER)  # fmt: skip


def part(doc, lang: dict) -> None:
    page_break(doc)
    par = para(doc, after=0)
    _font(par.add_run(f"{lang['part']} · {lang['lang']}"), 10, True, GREY)
    heading(doc, lang["title"], 1)
    para(doc, lang["subtitle"], 11, 8, GREY)
    para(doc, lang["intro"], 10, 8)
    table(doc, (lang["terms_h"], ""), [(f"**{a}**", b) for a, b in lang["terms"]], (4.2, 12.8))

    heading(doc, lang["how_h"], 2)
    for step in lang["how"]:
        para(doc, step, 10, 3, style="List Number")
    heading(doc, lang["score_h"], 3)
    table(doc, lang["score_cols"], [(f"**{a}**", b) for a, b in lang["score"]], (3.4, 13.6))
    heading(doc, lang["stages_h"], 3)
    para(doc, lang["stages_intro"], 10, 3)
    for item in lang["stages"]:
        para(doc, item, 10, 3, style="List Bullet")
    para(doc, lang["stages_out"], 10, 6)

    heading(doc, lang["block_h"], 2)
    para(doc, lang["block_intro"], 10, 3)
    for item in lang["block"]:
        para(doc, item, 10, 2, style="List Bullet")
    para(doc, lang["never"], 10, 6)

    for key, total, items in META:
        heading(doc, f"{key}. {lang['cat'][key]} — {total} {lang['points']}", 2)
        rows = [(cid, stage, pts, *lang["crit"][cid]) for cid, stage, pts in items]
        table(doc, lang["cols"], rows, (1.1, 1.3, 1.2, 8.6, 4.8), center=(0, 1, 2), stage_col=1)
    heading(doc, f"E. {lang['cat']['E']} — 10 {lang['points']}", 2)
    para(doc, lang["e_intro"], 10, 4)
    table(doc, lang["e_cols"], lang["e"], (1.1, 3.9, 6.0, 6.0), center=(0,))

    heading(doc, lang["sum_h"], 2)
    rows = [(f"{key}. {lang['cat'][key]}", s, b, s + b) for key, (s, b) in SPLIT.items()]
    rows.append((lang["total"], 63, 37, 100))
    table(doc, lang["sum_cols"], rows, (10.0, 2.3, 2.3, 2.4), center=(1, 2, 3), bold_last=True)

    heading(doc, lang["sheet_h"], 2)
    table(doc, lang["sheet_fields"], [("", "", "", "")], (4.25, 4.25, 4.25, 4.25), size=10)
    rows = [(f"{key}1 – {key}{len(items)}", total, "", "") for key, total, items in META]
    rows += [("E1 – E5", 10, "", ""), (lang["stage1"], 63, "", ""), (lang["full"], 100, "", "")]
    table(doc, lang["sheet_cols"], rows, (3.6, 2.4, 2.4, 8.6), center=(1, 2), size=10)
    para(doc, lang["sheet_foot"], 10, 8)

    heading(doc, lang["limits_h"], 2)
    para(doc, lang["limits_intro"], 10, 3)
    for item in lang["limits"]:
        para(doc, item, 9.5, 3, style="List Bullet")
    heading(doc, lang["src_h"], 3)
    for item in lang["src"]:
        para(doc, item, 9, 2, GREY)


def main() -> None:
    for lang in LANGS:  # every part must carry every criterion
        assert set(lang["crit"]) == {cid for _, _, items in META for cid, _, _ in items}, lang["lang"]
        assert [e[0] for e in lang["e"]] == ["E1", "E2", "E3", "E4", "E5"], lang["lang"]
    assert sum(t for _, t, _ in META) + 10 == 100
    assert all(sum(p for _, _, p in items) == total for _, total, items in META)
    assert sum(s for s, _ in SPLIT.values()) == 63 and sum(b for _, b in SPLIT.values()) == 37
    doc = Document()
    setup(doc)
    cover(doc)
    for lang in LANGS:
        part(doc, lang)
    doc.core_properties.title = "Grading criteria · Критерии оценки · Бағалау критерийлері"
    doc.core_properties.author = "Team Intuition"
    doc.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
