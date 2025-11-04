#!/bin/bash

# Python env setup
pipenv install -r requirements.txt

# OpenShift env setup
export $(cat .env | xargs)
oc login $OPENSHIFT_TOKEN

# start Python virtual env
pipenv shell