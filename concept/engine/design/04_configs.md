# 4. Конфиги

## 4.1. Формат и хранение

* Строгий JSON (UTF-8, без комментариев). Стандартная библиотека `json`.
* Один файл — одна сущность: `project`, `material`, `pipeline`, `ui`.
* Пресеты лежат рядом с проектом или в пакете; поиск идёт по слоям:
  `builtin → user → project → env → CLI`.
* Приоритет: чем ближе к пользователю, тем выше. Глубокий merge объектов;
  массивы заменяются целиком (иначе невозможно удалить этап).
* Все конфиги имеют `schema_version`. При загрузке применяются миграции.
* Конфиг не содержит путей, которые движок должен читать: движок получает уже
  разрешённый `ProcessingRequest`. Чтение файлов — задача адаптера/CLI.

## 4.2. `Project`

`Project` — это **состояние проекта у адаптера**, а не вход движка. Он хранит
настройки, ссылки на пресеты и план срезов.

```json
{
  "schema_version": "1.0",
  "project_id": "demo-lamp",
  "name": "Demo lamp shell",
  "source": {
    "host": "blender",
    "mesh_ref": "LampShell",
    "host_units": "m",
    "mesh_hash": "sha256:..."
  },
  "slice_plan": {
    "mode": "planar_stack",
    "origin_mm": [0, 0, 0],
    "axis": [0, 0, 1],
    "count": 2,
    "spacing_mm": 12.0,
    "offset_mm": 0.0,
    "u_hint": [1, 0, 0]
  },
  "material": {
    "preset_id": "pla-3mm",
    "overrides": {}
  },
  "pipeline": {
    "preset_id": "smooth-cut",
    "overrides": {
      "fillet_corners.radius_mm": 8.0
    }
  },
  "targets": {
    "roles": ["cut"],
    "tags_all": ["outer"]
  },
  "export": {
    "formats": ["svg"],
    "dir": "./out",
    "unit": "mm",
    "naming": "{project}/{slice_index:03d}"
  },
  "ui": {
    "schema_id": "preview/main",
    "last_panel": "processing"
  }
}
```

| Поле | Назначение |
| --- | --- |
| `source` | откуда меш и в каких единицах; хеш — для инвалидации кеша |
| `slice_plan` | как хост строит плоскости; движок это не читает |
| `material` | ссылка на пресет + точечные overrides |
| `pipeline` | ссылка на пайплайн + overrides по `method.param` |
| `targets` | какие контуры обрабатывать по умолчанию |
| `export` | настройки экспортёра (не движка) |
| `ui` | какой UI-схемой пользоваться и какую панель открыть |

`slice_plan.mode`:

| Mode | Смысл |
| --- | --- |
| `planar_stack` | набор параллельных плоскостей вдоль `axis` |
| `radial_fan` | плоскости, проходящие через ось, с шагом по углу |
| `custom_planes` | список плоскостей, заданных вручную (origin + normal) |

`radial_fan` дополнительно может иметь `angle_range_deg` и `count`. Выбор
плоскостей и построение кадров — адаптер.

## 4.3. `MaterialProfile`

Файл материала — самостоятельный пресет:

```json
{
  "schema_version": "1.0",
  "id": "pla-3mm",
  "name": "PLA sheet 3 mm",
  "thickness_mm": 3.0,
  "min_bend_radius_mm": 6.0,
  "max_bend_angle_deg": 120.0,
  "min_segment_mm": 0.4,
  "kerf_mm": 0.15,
  "k_factor": 0.42,
  "extra": {
    "density_g_cm3": 1.24
  }
}
```

Правило: **физика — в материале, допуски обработки — в операциях.** Не
добавляйте в материал `smoothing_iterations` или `simplify_tolerance`: это
параметры пайплайна, иначе один материал нельзя использовать в разных задачах.

## 4.4. `Pipeline`

```json
{
  "schema_version": "1.0",
  "id": "smooth-cut",
  "name": "Smooth cut contours",
  "description": "Fillet corners, lightly smooth, simplify, then densify for export.",
  "operations": [
    {
      "method": "fillet_corners",
      "params": {
        "radius_mm": 8.0,
        "min_turn_deg": 20.0,
        "arc_segments": 4,
        "mode": "error"
      }
    },
    {
      "method": "smooth",
      "params": {
        "algorithm": "chaikin",
        "iterations": 1,
        "preserve_corners_deg": 70.0,
        "max_deviation_mm": 0.2
      }
    },
    {
      "method": "simplify",
      "params": {
        "tolerance_mm": 0.05,
        "preserve_corners_deg": 70.0
      }
    },
    {
      "method": "densify",
      "params": {
        "max_spacing_mm": 2.0,
        "max_angle_step_deg": 12.0,
        "chord_tolerance_mm": 0.05
      }
    }
  ]
}
```

Правила:

* Порядок операций — это порядок в массиве. Он влияет на результат, поэтому
  входит в ключ кеша.
* `enabled: false` позволяет временно отключить этап, не удаляя настройки.
* `label` — только для GUI/логов; на расчёт не влияет.
* `target` на уровне операции переопределяет `targets` запроса.
* Пайплайн не содержит `normalize`/`validate`: они встроены в раннер.

## 4.5. Разрешение конфигов

Адаптер собирает запрос так:

```text
Project
  ├─ material: preset + overrides  ──► MaterialProfile
  ├─ pipeline: preset + overrides  ──► tuple[OperationSpec]
  ├─ targets                       ──► TargetSelector
  └─ slices: host slicing + frames ──► tuple[Slice]

                 ↓

ProcessingRequest (полный, самодостаточный)
```

Overrides применяются по пути `method.param`:

```json
{ "fillet_corners.radius_mm": 8.0, "smooth.iterations": 2 }
```

Если операции с таким методом нет — это ошибка конфигурации (`E_PARAM`), а не
молчаливое создание новой операции. Для добавления операции используется
`operations_append` (явный список), чтобы поведение было предсказуемым.

## 4.6. GUI-конфиг

GUI-схема — отдельный слой. Она **не дублирует** defaults и границы методов:
они берутся из `EngineDescriptor`. Схема задаёт раскладку, привязки и события.

```json
{
  "schema_version": "1.0",
  "id": "preview/main",
  "title": "Slice Engine",
  "layout": {
    "type": "panel",
    "children": [
      {
        "type": "group",
        "title": "Material",
        "children": [
          {"type": "select", "bind": "project.material.preset_id",
           "source": "materials", "label": "Preset"},
          {"type": "number", "bind": "material.thickness_mm",
           "label": "Thickness", "unit": "mm", "step": 0.1}
        ]
      },
      {
        "type": "group",
        "title": "Processing",
        "children": [
          {"type": "method_form", "method": "fillet_corners",
           "bind": "pipeline.operations[0].params"},
          {"type": "method_form", "method": "smooth",
           "bind": "pipeline.operations[1].params"}
        ]
      },
      {
        "type": "row",
        "children": [
          {"type": "button", "label": "Preview", "event": "preview.requested"},
          {"type": "button", "label": "Apply", "event": "process.requested"}
        ]
      }
    ]
  },
  "events": {
    "preview.requested": {
      "action": "engine.process",
      "debounce_ms": 150,
      "target": "preview"
    },
    "project.changed": {
      "action": "runtime.invalidate",
      "targets": ["preview", "result"]
    }
  }
}
```

Типы элементов v1: `panel`, `group`, `row`, `column`, `tabs`, `select`, `number`,
`text`, `checkbox`, `slider`, `method_form`, `button`, `label`, `separator`,
`scroll`. Конкретный виджет выбирает адаптер.

Правила GUI-схемы:

* `bind` — путь в runtime state (`project.*`, `material.*`, `pipeline.*`,
  `selection.*`), а не имя Python-переменной.
* `method_form` автоматически строит поля по `MethodDescriptor.params`.
  Явные поля внутри формы — только для переопределения раскладки.
* Условия видимости — декларативные (`visible_when`), без исполнения кода.
* События — имена тем; обработчик живёт в `AppController`, а не в конфиге.
* GUI-схема версионируется отдельно (`schema_version`), чтобы можно было
  менять интерфейс, не трогая движок.
* Один и тот же `method_form` может использоваться в Blender, Qt и браузере:
  различается только реализация `Builder`.

## 4.7. События и пересчёт

Минимальный набор тем:

| Тема | Когда | Кто слушает |
| --- | --- | --- |
| `state.changed` | изменилось значение в runtime | preview, controller |
| `selection.changed` | изменился активный срез/контур | controller, GUI |
| `process.requested` | пользователь нажал «Применить» | controller |
| `process.started` | запрос ушёл в движок | GUI (спиннер) |
| `process.completed` | результат получен | runtime, preview, GUI |
| `process.failed` | результат `ERROR` | GUI, лог |
| `preview.requested` | нужен быстрый предпросмотр | controller |
| `export.requested` | экспорт | ExportManager |

Пересчёт по изменению параметра должен быть **debounce** (например, 150 мс) и
отменяемым: если пришёл новый запрос, старый результат игнорируется по
`request_id`/поколению. Движок чистый, поэтому отмена — это просто отбрасывание
результата; прерывать вычисление не обязательно в v1.

## 4.8. Ошибки конфигурации

| Ситуация | Код |
| --- | --- |
| нет пресета материала/пайплайна | `E_CONFIG_NOT_FOUND` |
| override указывает на несуществующий метод/параметр | `E_CONFIG_OVERRIDE` |
| `bind` в GUI-схеме указывает в никуда | `E_CONFIG_BIND` |
| неизвестный тип виджета | `E_CONFIG_WIDGET` |
| циклическая зависимость `visible_when` | `E_CONFIG_CONDITION` |

Ошибки конфигурации обнаруживаются при загрузке проекта/старте плагина, а не в
момент нажатия кнопки. Это важно для UX: пользователь должен видеть проблему
сразу.

## 4.9. Файлы примеров

* [examples/project.example.json](examples/project.example.json)
* [examples/material.pla.example.json](examples/material.pla.example.json)
* [examples/pipeline.smooth-cut.example.json](examples/pipeline.smooth-cut.example.json)
* [examples/ui.schema.example.json](examples/ui.schema.example.json)
