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
	docker compose -f docker-compose.yaml -f docker-compose.dev.yaml up -d --build --remove-orphans
	make logs
dev-stop:
	docker compose -f docker-compose.yaml -f docker-compose.dev.yaml down
	docker compose rm -f 
# make prod
prod: requirements
	cp .env-prod .env
	docker compose up -d --build
prod-stop:
	docker compose down

VERSION := $(shell git describe --tags `git rev-list --tags --max-count=1` 2>/dev/null || git rev-parse --short HEAD)
docker-scan:
	docker pull aquasec/trivy:0.18.3
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v $(pwd)/.cache:/root/.cache/ aquasec/trivy:0.18.3 lbr88/mmchatgpt:latest
docker-build: requirements
	docker build -t docker.io/lbr88/mmchatgpt:$(VERSION) -t docker.io/lbr88/mmchatgpt:latest -t ghcr.io/aio-it/mmchatgpt:$(VERSION) -t ghcr.io/aio-it/mmchatgpt:latest .
docker-push: docker-build
	cat .github-token | docker login ghcr.io -u lbr88 --password-stdin
	cat .docker-token | docker login docker.io -u lbr88 --password-stdin
	docker push docker.io/lbr88/mmchatgpt:$(VERSION)
	docker push docker.io/lbr88/mmchatgpt:latest
	docker push ghcr.io/aio-it/mmchatgpt:latest
	docker push ghcr.io/aio-it/mmchatgpt:$(VERSION)
# other
requirements:
	echo "Generating requirements.txt"
	PIPENV_VERBOSITY=-1 pipenv requirements > requirements.txt
logs:
	docker compose logs -f
test:
	pipenv run coverage run -m pytest tests
	pipenv run coverage report
release-patch: requirements
	./make-release.sh patch
release-minor: requirements
	./make-release.sh minor
release-major: requirements
	./make-release.sh major