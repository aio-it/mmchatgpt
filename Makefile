.PHONY : all dev prod
all: dev
dev: dev-stop requirements
	cp .env-dev .env
	docker-compose up -d --build
dev-stop:
	docker-compose down
	docker-compose rm -f

prod: requirements
	cp .env-prod .env
	docker-compose up -d --build
requirements:
	echo "Generating requirements.txt"
	PIPENV_VERBOSITY=-1 pipenv requirements > requirements.txt
logs:
	docker-compose logs -f