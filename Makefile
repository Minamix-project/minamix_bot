deploy:
	git pull --ff-only && git fetch --tags && BOT_VERSION=$$(git describe --tags --always) GIT_COMMIT=$$(git rev-parse --short HEAD) DEPLOY_NOTIFICATION=1 docker compose up -d --build bot backup

restart:
	DEPLOY_NOTIFICATION=0 docker compose up -d --force-recreate bot

stop:
	docker compose stop bot backup

logs:
	docker compose logs -f bot

status:
	docker compose ps
