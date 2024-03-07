.PHONY : all dev prod
all: test dev
#make clean
clean:
	docker compose down
	docker compose rm -f
	docker volume prune --all -f
# make dev
dev: test dev-stop requirements
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
# other
requirements:
	echo "Generating requirements.txt"
	PIPENV_VERBOSITY=-1 pipenv requirements > requirements.txt
logs:
	docker compose logs -f
test:
	pipenv run python -m pytest -v
