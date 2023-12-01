# PappayaLite CRM with Odoo 14 build

Uses bitnami odoo docker base image as start to make it work with helm charts.

## Deploy

1. Create `kube` file in `config` folder based on `kube-sample`.
1. Create `ssl-cert` and `ssl-key` files in `config` folder based on their sample files. This will be the pappayalite wildcard SSL details.
1. Build the image ```docker build -t registry.pappayacloud.com:5000/pappayalite-crm:0.0.1 .```
1. Push the image to repository ```docker push registry.pappayacloud.com:5000/pappayalite-crm:0.0.1```
1. Run the build python script to deploy to kubernetes ```python3 build.py```

## Development
This is a staging setup. Need to have separate docker setup for development with addons folder mounted.

1. Create `kube` file in `config` folder based on `kube-sample`.
1. Create `ssl-cert` and `ssl-key` files in `config` folder based on their sample files. This will be the pappayalite wildcard SSL details.

## Build
To make an docker image with custom addons included:

1. Run ```docker build -t <build_name:build_version> .```
1. Push the docker image to required repository

## Local view
To run the build locall with database, use docker compose command ```docker-compose up``` which will start both the odoo build and postgres and create a default user account as below:

```
Username: user@pappaya.com
Password: pappaya
```

## Control odoo process in build

### To start or stop odoo process
Find the docker container id for odoo by running ```docker ps -a``` and run ```docker exec -it <container_id> bash``` which will take you to the containers bash. Run the following in there:

* START: ```nami start odoo```
* STOP: ```nami stop odoo```
* RESTART: ```nami restart odoo```

### Run module install commands in instance
1. Get into container bash as mentioned above.
1. Stop odoo service ```nami stop odoo```
1. Switch to user "odoo"
1. Go to folder ```cd /opt/bitnami/odoo```
1. Run ```/opt/bitnami/odoo/venv/bin/python openerp-server --config openerp-server.conf --stop-after-init -u pappaya_core &``` to update pappaya_core module.
1. Can run other install or update calls similarly.
