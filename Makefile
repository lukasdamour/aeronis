.PHONY: build up down logs restart shell up-offline down-offline

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

restart:
	docker compose restart

shell:
	docker compose exec app /bin/bash