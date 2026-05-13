# ♟ Chess Correspondence RSS

Генерирует RSS-ленту с ходами противников в партиях по переписке
на **chess.com** и **lichess.org**. Запускается автоматически через GitHub Actions,
никнеймы хранятся в GitHub Secrets — в коде их нет.

---

## Быстрая настройка (≈15 минут)

### Шаг 1 — Создать публичный репозиторий на GitHub

1. Зайди на [github.com/new](https://github.com/new)
2. Название — любое, например `chess-rss`
3. Visibility: **Public** ✅
4. Нажми **Create repository**
5. Загрузи все файлы из этого архива
   (веб-интерфейс: кнопка **Add file → Upload files**)

### Шаг 2 — Добавить никнеймы как секреты

Никнеймы не будут видны в коде — они хранятся в зашифрованных переменных GitHub.

1. В репозитории: **Settings** → **Secrets and variables** → **Actions**
2. Нажми **New repository secret** и добавь два секрета:

| Name | Secret |
|---|---|
| `CHESSCOM_USERNAME` | твой ник на chess.com |
| `LICHESS_USERNAME` | твой ник на lichess.org |

Если играешь только на одной платформе — добавь только один,
второй просто не добавляй (скрипт пропустит).

### Шаг 3 — Включить GitHub Pages

1. В репозитории: **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / папка: `/docs`
4. Нажми **Save**

Через минуту RSS будет доступен по адресу:
```
https://ВАШ_ЛОГИН.github.io/ВАШ_РЕПОЗИТОРИЙ/feed.xml
```

### Шаг 4 — Первый запуск вручную

1. Вкладка **Actions** в репозитории
2. Слева: `Update Chess RSS Feed`
3. **Run workflow** → **Run workflow**
4. Подожди ~30 секунд — появится зелёная галочка ✅

После этого Actions запускается автоматически раз в час.

### Шаг 5 — Подписаться в RSS-ридере

Скопируй URL ленты из Шага 3 и добавь в ридер:

| Ридер | Платформа |
|---|---|
| **Reeder 5** | iOS / macOS |
| **NetNewsWire** | iOS / macOS (бесплатный) |
| **Feedly** | iOS / Android / Web |
| **Inoreader** | iOS / Android / Web |

---

## Расписание

По умолчанию — **раз в час**. Меняется в `.github/workflows/update-feed.yml`:

```yaml
- cron: "0 * * * *"      # раз в час
- cron: "0 7 * * *"      # раз в день в 09:00 по Цюриху (летом)
- cron: "0 7,17 * * *"   # дважды в день
```

---

## Что показывает RSS

Каждая запись = партия, где **противник уже походил и ждёт твоего хода**:

```
♟ chess.com | vs opponent_nick (ты white) → Nf6
  Противник сделал ход: Nf6. Ходов в партии: 14. Твой ход!
```

- 🆕 — ход новый с момента прошлой проверки
- Если ходов нет — «Нет партий, ожидающих твоего хода»

---

## Возможные проблемы

- **feed.xml пустой** — нет активных партий или опечатка в секрете
- **Lichess 403** — профиль приватный; создай токен на
  [lichess.org/account/oauth/token](https://lichess.org/account/oauth/token),
  добавь как секрет `LICHESS_TOKEN`
- **Actions не запускается** — во вкладке Actions нажми
  «I understand my workflows, go ahead and enable them»
