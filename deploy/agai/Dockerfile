# The agent team (CodeFix AI, the separate AGAI project) as it runs next to the
# doctor. Nothing of AGAI is copied here: the base image is built from AGAI's own
# checkout with AGAI's own Dockerfile (deploy/agai/build.sh), and this layer only
# adds what working on THIS repository needs:
#
#   * our test suite's dependencies - AGAI's Tester runs `pytest` on a clone of
#     this repo with AGAI's own Python, so patient/doctor imports must resolve;
#   * git settings - the repo is mounted from the host (another owner), and the
#     PR agent pushes to GitHub with the token from the environment.
ARG AGAI_BASE=aid/agai-base:local
FROM ${AGAI_BASE}

RUN pip install --no-cache-dir \
      pypdf==6.15.0 psutil==7.2.2 prometheus-client==0.23.1 python-multipart jsonschema openai \
 && git config --system safe.directory '*' \
 && git config --system credential.https://github.com.helper \
      '!f() { test "$1" = get || exit 0; echo username=x-access-token; echo "password=${GITHUB_TOKEN}"; }; f'
