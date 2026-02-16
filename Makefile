IMAGE_NAME = portfolio-bot

.PHONY: build run clean stop

build:
	docker compose build

run:
	docker compose up -d

logs:
	docker compose logs -f

stop:
	docker compose down

clean:
	docker system prune -f
