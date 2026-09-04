deploy:
	git pull && docker compose up -d --build bot backup

restart:
	docker compose restart bot

stop:
	docker compose stop bot backup

logs:
	docker compose logs -f bot

status:
	docker compose ps
