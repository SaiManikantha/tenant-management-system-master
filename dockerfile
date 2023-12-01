FROM bitnami/odoo:14.0.20210510-debian-10-r12

RUN apt-get update
RUN apt-get --assume-yes install python-dev
RUN apt-get --assume-yes install gcc

RUN /bin/bash -c "source /opt/bitnami/odoo/venv/bin/activate \
    && pip install openpyxl \
    && deactivate"

COPY ./addons /opt/bitnami/odoo/odoo/addons

CMD ["nami", "start", "--foreground", "odoo"]