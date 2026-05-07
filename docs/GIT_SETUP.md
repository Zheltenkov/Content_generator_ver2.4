# Настройка доступа к GitHub

## Текущая конфигурация

- **Remote:** `origin` → `git@github.com:Zheltenkov/Content_generator_ver1.git` (SSH)
- **SSH к GitHub:** работает (под пользователем Zheltenkov)

Ошибка «Repository not found» означает, что репозиторий на GitHub ещё не создан.

---

## Шаг 1: Создать репозиторий на GitHub

1. Откройте https://github.com/new
2. **Repository name:** `Content_generator_ver1` (или как у вас в remote)
3. **Visibility:** Private или Public — по желанию
4. **Не** ставьте галочки «Add a README», «Add .gitignore» — у вас уже есть локальный проект
5. Нажмите **Create repository**

---

## Шаг 2: Отправить код

После создания репозитория выполните в папке проекта:

```powershell
git push -u origin main
```

Если ветка у вас называется `master`:

```powershell
git branch -M main
git push -u origin main
```

---

## Если имя репозитория или аккаунт другие

Проверьте имя и владельца репозитория на GitHub, затем обновите remote:

```powershell
# Посмотреть текущий remote
git remote -v

# Заменить URL (если создали репозиторий с другим именем/под организацией)
git remote set-url origin git@github.com:Zheltenkov/ИМЯ_РЕПОЗИТОРИЯ.git

# Или использовать HTTPS (логин + Personal Access Token при запросе пароля)
git remote set-url origin https://github.com/Zheltenkov/Content_generator_ver1.git
```

---

## Доступ по HTTPS вместо SSH

Если хотите пушить по логину и паролю (токену):

```powershell
git remote set-url origin https://github.com/Zheltenkov/Content_generator_ver1.git
git push -u origin main
```

При запросе пароля укажите **Personal Access Token** (не пароль от аккаунта):  
GitHub → Settings → Developer settings → Personal access tokens → Generate new token (с правом `repo`).
