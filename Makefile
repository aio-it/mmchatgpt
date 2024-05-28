.PHONY : all dev prod
all: test dev
#make clean
clean:
	docker compose down
	docker compose rm -f
	docker volume prune --all -f
# make dev
dev: dev-stop docker-build
	cp .env-dev .env
	docker compose up -d --build
	make logs
dev-stop:
	docker compose down
	docker compose rm -f
# make prod
prod: requirements
	cp .env-prod .env
	docker compose up -d --build
prod-stop:
	docker compose down

VERSION := $(shell git describe --tags `git rev-list --tags --max-count=1` 2>/dev/null || git rev-parse --short HEAD)
docker-build: requirements
	docker build -t lbr88/mmchatgpt:$(VERSION) -t lbr88/mmchatgpt:latest .
docker-push: docker-build
	docker push lbr88/mmchatgpt:$(VERSION)
	docker push lbr88/mmchatgpt:latest
# other
requirements:
	echo "Generating requirements.txt"
	PIPENV_VERBOSITY=-1 pipenv requirements > requirements.txt
logs:
	docker compose logs -f
test:
	pipenv run coverage run -m pytest tests
	pipenv run coverage report