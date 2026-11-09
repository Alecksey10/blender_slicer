# 1. Архитектура

## 1.1. Цели

Движок — независимая вычислительная библиотека, которая:

1. принимает **2D-контуры срезов** и параметры обработки;
2. применяет к ним упорядоченный пайплайн геометрических операций;
3. проверяет ограничения материала и геометрии;
4. возвращает новые контуры, метрики и диагностику;
5. не хранит состояние между вызовами;
6. не импортирует хост (Blender, Unreal, Qt) и не знает о 3D.

Главное правило: **всё, что связано с 3D, находится в адаптере; всё, что связано
с геометрией в плоскости, — в движке.**

## 1.2. Слои

```text
┌──────────────────────────────────────────────────────────────┐
│ HOST: Blender / Unreal / Qt / CLI                            │
│  меш, плоскости, выделение, отображение, файлы проекта       │
└───────────────────────────┬──────────────────────────────────┘
                            │ host API
┌───────────────────────────▼──────────────────────────────────┐
│ ADAPTER (плагин под конкретный хост)                         │
│  • пересечение меша с плоскостями (host slicing)             │
│  • CoordinateFrame: 3D ↔ 2D                                  │
│  • RuntimeState: проект, кадры, срезы, результаты, кеш       │
│  • EventBus, GUI builder, обработчик бизнес-логики           │
│  • визуализация и экспорт                                    │
└───────────────┬───────────────────────────────┬──────────────┘
                │ ProcessingRequest/Result      │ те же данные
                │ (JSON или Python-объекты)     │
┌───────────────▼────────────────┐   ┌──────────▼──────────────┐
│ ENGINE (чистые функции)        │   │ PREVIEW                 │
│  facade → pipeline → methods   │   │  SVG / HTML / ASCII     │
│  registry, validation, JSON    │   │  без хоста и без GUI    │
└───────────────┬────────────────┘   └──────────┬──────────────┘
                │                               │
        ┌───────▼───────────────────────────────▼───────┐
        │ PROTOCOL: типы, JSON-кодек, дескрипторы,     │
        │ коды ошибок, версии                          │
        └───────────────────────────────────────────────┘
```

### Правила зависимостей

| Пакет | Может импортировать | Не может импортировать |
| --- | --- | --- |
| `slicer_protocol` | только стандартную библиотеку | engine, adapters, preview |
| `slicer_engine` | protocol + stdlib | adapters, preview, хост |
| `slicer_preview` | protocol + stdlib | engine methods, adapters, хост |
| `slicer_adapters` | protocol, фасад engine, preview, host SDK | внутренности методов engine |
| `slicer_app` | всё перечисленное | — (composition root) |

Правило проверяется тестом: AST-скрипт обходит `import`-ы и падает при нарушении.
Это дешевле, чем потом распутывать циклические зависимости.

## 1.3. Пакеты и модули

```text
slicer_protocol/
  __init__.py
  version.py          # PROTOCOL_VERSION, SCHEMA_VERSION
  units.py            # mm/deg, проверка конечных чисел
  types.py            # Point2, Vec3, Range, Limits
  geometry.py         # Contour, Slice, FoldSpec, ContourRole
  material.py         # MaterialProfile
  operations.py       # OperationSpec, TargetSelector, FailurePolicy
  request.py          # ProcessingRequest, RequestOptions
  result.py           # ProcessingResult, SliceResult, ContourResult, Metrics
  diagnostics.py      # Diagnostic, Severity, ErrorCode
  descriptor.py       # ParamSpec, MethodDescriptor, EngineDescriptor
  json_codec.py       # dataclasses ↔ JSON, канонический JSON
  schema.py           # структурная валидация без pydantic
  migrate.py          # миграции schema_version

slicer_engine/
  __init__.py         # публичный фасад
  facade.py           # Engine: descriptor / validate / process / process_json
  registry.py         # MethodRegistry, регистрация встроенных методов
  pipeline/
    runner.py         # normalize → operations → validate
    selection.py      # TargetSelector → конкретные контуры
    policies.py       # strict / per_slice / best_effort
    state.py          # изменяемое состояние одного среза внутри вызова
  methods/
    base.py           # Method Protocol, MethodContext, StageOutput
    normalize.py
    resample.py
    simplify.py
    smooth.py
    fillet.py
    densify.py
    curvature.py
    local.py
    bend_check.py
    repair.py
  validation/
    invariants.py     # геометрические инварианты
    limits.py         # лимиты точек/срезов/операций
  cli.py              # python -m slicer_engine describe|validate|process

slicer_preview/
  __init__.py
  svg.py              # рендер одного/нескольких срезов
  html.py             # контактный лист
  layout.py           # сетка, масштаб, подписи
  palette.py          # цвета ролей/диагностики
  cli.py              # python -m slicer_preview request.json result.json

slicer_adapters/
  base/
    host.py           # HostAdapter Protocol
    frames.py         # CoordinateFrame, FrameMapper, FrameStore
    runtime.py        # ProjectState, Cache, UndoStack
    events.py         # EventBus, темы событий
    engine_client.py  # in-process или RPC-клиент
    ui.py             # Widget/Builder/GuiConfig Protocol
    export.py         # ExportManager
  preview_adapter/    # локальный адаптер для разработки без Blender
  blender/            # bpy-реализация
  qt/                 # заготовка
  unreal/             # заготовка

slicer_app/
  main.py             # composition root для standalone/CLI
  controller.py       # “хранитель основной логики” из концепции
```

Пакет `slicer_protocol` намеренно отделён от движка: адаптеры и предпросмотр
зависят от **контракта**, а не от версии алгоритмов. Это и есть Core Protocol
Version из концепции.

## 1.4. Владение состоянием

| Данные | Владелец | Время жизни |
| --- | --- | --- |
| Меш, плоскости, материалы хоста | HOST | сессия хоста |
| `Project` (настройки) | адаптер / config store | проект |
| `CoordinateFrame` | адаптер (`FrameStore`) | до изменения плана срезов |
| Исходные `Slice` | адаптер (`RuntimeState`) | проект |
| `ProcessingRequest` | адаптер, собирается на вызов | один вызов |
| `ProcessingResult` | адаптер (`Cache`) | до инвалидации |
| Выделение, активный срез | адаптер | UI-сессия |
| Внутренние буферы движка | движок | только стек вызова |

В движке **нет** глобального изменяемого состояния. Реестр методов — статическая
неизменяемая таблица; дескрипторы можно кешировать, но они не зависят от запроса.

## 1.5. Жизненный цикл вызова

```text
1. Пользователь меняет параметр в GUI.
2. AppController публикует state.changed.
3. Адаптер пересобирает затронутые Slice (если изменилась геометрия/план).
4. Adapter.ResolveConfig: preset_id + overrides → полный ProcessingRequest.
5. EngineClient.process(request)  [в фоновом потоке]
6. Engine: validate → normalize → operations → final validate.
7. ProcessingResult возвращается адаптеру.
8. Адаптер проверяет round-trip 2D→3D и обновляет runtime state.
9. Preview/Visualization получает result и перерисовывает срезы.
10. Пользователь нажимает «Экспорт» → ExportManager.
```

Шаги 5–7 не знают, откуда пришёл запрос. Шаги 1–4 и 8–10 не знают, каким
алгоритмом обработан срез.

## 1.6. Версионность

Четыре независимые версии:

| Версия | Где живёт | Что ломает |
| --- | --- | --- |
| `host_api_version` | адаптер | несовместимость с API Blender/Unreal/Qt |
| `protocol_version` | `slicer_protocol` | структура запроса/результата |
| `schema_version` | каждый JSON-конфиг | поля конфига |
| `engine_version` | движок | поведение алгоритмов |

Правила:

* `protocol_version` — semver. Несовпадение **major** → запрос отклоняется
  с `E_PROTOCOL_VERSION` до обработки. Новее **minor** → предупреждение.
* `schema_version` проверяется кодеком; миграции применяются цепочкой
  `migrate_1_0_to_1_1`, `migrate_1_1_to_1_2`.
* `descriptor()` возвращает поддерживаемые версии и лимиты; адаптер сверяет их
  при инициализации, а не в момент нажатия кнопки.
* В результат всегда попадает `engine.version` и `protocol_version`, чтобы
  сохранённый результат можно было воспроизвести.

## 1.7. Детерминизм и потоки

* В выходных данных нет случайности, времени и путей файловой системы.
  Тайминги (`duration_ms`) — только в отдельной секции `metrics.timing` и
  исключаются из сравнения golden-файлов.
* Порядок срезов и контуров сохраняется; новые контуры получают
  детерминированные ID (`<parent>#1`, `<parent>#2`, …), а не UUID.
* Контрактные типы неизменяемы (`frozen=True`, кортежи). Внутри метода
  допускаются изменяемые списки — они не покидают вызов.
* `Engine.process()` потокобезопасен, если реестр не мутируется. Адаптер
  сериализует доступ к `RuntimeState`; тяжёлый вызов уходит в worker-поток,
  результат возвращается в UI-поток через планировщик хоста.
* Кеш: ключ = SHA-256 от канонического JSON запроса + `engine_version`.
  Инвалидация — при изменении материала, операций, геометрии среза или плана
  срезов. Кеш живёт в адаптере; движок о нём не знает.

## 1.8. Точки расширения

| Что расширяем | Как | Что не меняется |
| --- | --- | --- |
| Новый алгоритм | `Method` + `MethodDescriptor` + регистрация | фасад, контракт, GUI-схема |
| Новый хост | новый пакет в `slicer_adapters` | движок и протокол |
| Новый формат экспорта | `ExportManager` в адаптере | геометрия и результат |
| Новый рендер | новый модуль в `slicer_preview` | контракт |
| 3D-unfold / offset / kerf | отдельный будущий пакет или метод с явным контрактом | ядро v1 |

Расширение методов не требует правок `Engine`: реестр передаётся в конструктор
или дополняется до первого вызова. Динамическая загрузка стороннего кода из
файлов не предусмотрена в v1 — это вопрос доверия и безопасности.
