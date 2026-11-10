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
| `blender_slicer.protocol` | только стандартную библиотеку | engine, spatial, adapters, preview |
| `blender_slicer.spatial` | protocol + stdlib | engine, adapters, preview, хост |
| `blender_slicer.engine` | protocol + spatial + stdlib | adapters, preview, хост |
| `blender_slicer.preview` | protocol + stdlib | engine methods, adapters, хост |
| `blender_slicer.adapters` | protocol, spatial, фасад engine, preview, host SDK | внутренности методов engine |
| `blender_slicer.app` | всё перечисленное | — (composition root) |

Правило проверяется тестом: AST-скрипт обходит `import`-ы и падает при нарушении.
Это дешевле, чем потом распутывать циклические зависимости.

## 1.3. Пакеты и модули

```text
blender_slicer/
  __init__.py         # bl_info, ленивая регистрация (без импорта bpy)
  protocol/
    version.py        # PROTOCOL_VERSION, SCHEMA_VERSION
    units.py          # мм/градусы, проверка конечных чисел
    types.py          # umbrella-реэкспорт публичных типов
    shapes.py         # Contour, Slice (включая offset_mm), FoldSpec, ContourRole
    material.py       # MaterialProfile, section_radius, clearance
    operations.py     # OperationSpec, TargetSelector, FailurePolicy
    request.py        # ProcessingRequest, RequestOptions
    result.py         # ProcessingResult, SliceResult, ContourResult, Metrics
    diagnostics.py    # Diagnostic, Severity, ErrorCode
    geometry.py       # normalize, signed_area, fillet_corners, collapse_collinear
    offset.py         # offset_polyline: miter/round/bevel + предупреждения
    shrink.py         # shrink_points: ужимание сечения к центру
    json_codec.py     # dataclasses ↔ JSON, loads_result
  spatial/
    vectors.py        # 3D-векторы без внешних библиотек
    frames.py         # CoordinateFrame, FrameStore, verify_roundtrip
    contacts.py       # find_contacts, ContactPoint
  engine/
    __init__.py       # публичный фасад
    facade.py         # Engine: descriptor / validate / process / process_parallel
    registry.py       # MethodRegistry, регистрация встроенных методов
    parallel.py       # split_request, merge_results, ThreadPoolExecutor
    pipeline/
      runner.py       # normalize → offset → operations → validate
      selection.py    # TargetSelector → конкретные контуры
      policies.py     # strict / per_slice / best_effort
      state.py        # изменяемое состояние одного среза внутри вызова
    methods/
      base.py         # Method Protocol, MethodContext, StageOutput
      normalize.py, resample.py, simplify.py, smooth.py, fillet.py,
      densify.py, curvature.py, bend_check.py, local.py, repair.py,
      offset.py       # offset_contour — отступ как метод пайплайна
      shrink.py       # shrink_section — ужимание + сглаживание
    validation/
      invariants.py   # геометрические инварианты
      limits.py       # лимиты точек/срезов/операций
    cli.py            # describe | validate | process --workers
  preview/
    svg.py            # render_result_svg, render_layers_svg
    cli.py            # предпросмотр без GUI
  adapters/
    base/
      host.py         # HostAdapter Protocol
      plan.py         # SlicePlan, CutOffsetPolicy (X outward, Z inward)
      layers.py       # SliceLayer, LayerStore — итерации срезов
      runtime.py      # RuntimeState: слои, кадры, результаты
      events.py       # EventBus, темы событий
      engine_client.py# клиент движка, решает про потоки
      controller.py   # AppController — «хранитель логики»
      ui.py           # Widget/Builder/GuiConfig Protocol
      visualization.py# общий контракт отрисовки
      export.py       # ExportManager
    blender/
      adapter.py      # мост настроек Blender → план/запрос
      host.py         # BlenderHost
      slicing.py      # меш + плоскости → Slice/Frames
      visualization.py# кривые слоёв и контакты
      panels.py       # панели Slice и Layers
      operators.py    # генерация, обработка, контакты, слои, экспорт
      properties.py   # SlicerSettings
      ui_schema.py    # декларативные секции полей
      settings_io.py  # экспорт/импорт настроек
      i18n.py         # регистрация каталога в bpy.app.translations
  i18n/
    __init__.py       # SUPPORTED_LOCALES, t(), normalize_locale
  app/
    controller.py     # реэкспорт AppController из adapters.base
    main.py           # standalone CLI (--request/--svg/--workers)
```

`spatial` выделен отдельно: кадры и контакты — это 3D, но они не зависят от
хоста. Движок по-прежнему видит только 2D и `frame_id`.

Слои (`SliceLayer`/`LayerStore`) — тоже уровень адаптера: один слой на план
срезов, поэтому X- и Z-проходы хранятся, обрабатываются и рисуются вместе, но
независимо.

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
* Решение о многопоточности принимает клиент (`EngineClient`), а движок лишь
  исполняет: `Engine.process_parallel` делит запрос на непрерывные чанки и
  сливает результаты в исходном порядке. `FailurePolicy.STRICT` всегда идёт
  последовательным путём, чтобы отмена целого запроса не изменила смысл.
  Хост без потоков передаёт `workers=1` и использует тот же код.
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
| Новый отступ / kerf-политика | параметры `offset_contour` или новый метод | пайплайн, контракт |
| Новый анализ сборки | модуль в `spatial/` (как `contacts.py`) | движок и протокол |
| 3D-unfold / сборка модели | отдельный будущий пакет | ядро v1 |

Расширение методов не требует правок `Engine`: реестр передаётся в конструктор
или дополняется до первого вызова. Динамическая загрузка стороннего кода из
файлов не предусмотрена в v1 — это вопрос доверия и безопасности.
