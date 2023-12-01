from avionix import ChartBuilder, ChartDependency, ChartInfo
from avionix.kube.core import Namespace
from avionix.chart.utils import get_helm_installations
from avionix._process_utils import custom_check_output
from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes.client.rest import ApiException
from pydantic import BaseModel
from typing import Optional
import base64, os, sys, getopt, json


# GLOBALS
deployment_mode = 'development'


class BuildParam(BaseModel):
    namespace: str
    build_name: str
    build_domain: str
    odoo_username: Optional[str] = 'admin@pappaya.com'
    app_registry: Optional[str] = 'registry.pappayacloud.com:5000'
    app_repository: Optional[str] = 'pappayalite-crm'
    app_version: Optional[str] = 'latest'
    max_cpu: Optional[str] = '1000m'
    max_memory: Optional[str] = '2024Mi'
    storage_class: Optional[str] = ''
    smtp_host: Optional[str] = ''
    smtp_port: Optional[str] = ''
    smtp_user: Optional[str] = ''
    smtp_password: Optional[str] = ''
    smtp_protocol: Optional[str] = ''


class BuildStatus(BaseModel):
    build_status: str
    odoo_pod_status: Optional[str]
    odoo_app_status: Optional[str]
    postgresql_pod_status: Optional[str]
    postgresql_app_status: Optional[str]


def kubeconfig():
    kube_config_path = os.path.dirname(os.path.realpath(__file__)) + '/config/' + deployment_mode + '/kube.yaml'
    os.environ['KUBECONFIG'] = kube_config_path
    config.load_kube_config(config_file=kube_config_path)


def set_role_binding(namespace):
    kubeconfig()
    kube_v1 = client.RbacAuthorizationV1Api()
    body = client.V1alpha1RoleBinding(
        kind='RoleBinding',
        metadata=client.V1ObjectMeta(name='system:openshift:scc:anyuid', namespace=namespace),
        role_ref=client.V1alpha1RoleRef('rbac.authorization.k8s.io', 'ClusterRole', 'system:openshift:scc:anyuid'),
        subjects=[
            client.V1alpha1Subject(kind='ServiceAccount', name='default', namespace=namespace)
        ]
    )
    try:
        kube_v1.read_namespaced_role_binding('system:openshift:scc:anyuid', namespace, pretty=True)
    except ApiException as e:
        print('Role binding not found. Creating one...')
        try:
            kube_v1.create_namespaced_role_binding(namespace, body)
        except ApiException as e:
            print('Failed to create role binding: %s' % e)


def define_chart_builder(namespace, build_name, odoo_values, app_version):
    return ChartBuilder(
        ChartInfo(
            api_version='3.2.4',
            name=build_name,
            version='0.1.0',
            app_version=app_version,
            dependencies=[
                ChartDependency(
                    'odoo',
                    '18.2.2',
                    'https://charts.bitnami.com/bitnami',
                    'bitnami',
                    values=odoo_values,
                )
            ],
        ),
        [],
        'charts',
        True,
        namespace,
    )


def build_initial(chart_builder):
    kubeconfig()
    if chart_builder.is_installed:
        print('Already installed')
        return 0
    else:
        print('Installing...')
        chart_builder.install_chart(
            options={'create-namespace': None, 'dependency-update': None}
        )
        set_role_binding(chart_builder.namespace)
        return 1


def build_upgrade(chart_builder, build_name, odoo_values, app_version):
    kubeconfig()
    if chart_builder.is_installed:
        print('Upgrading...')
        kube_v1 = client.CoreV1Api()

        # Extract passwords for upgrade
        odoo_secret = kube_v1.read_namespaced_secret(
            name=build_name + '-odoo', namespace=chart_builder.namespace
        )
        odoo_values['odooPassword'] = base64.standard_b64decode(
            odoo_secret.data['odoo-password']
        ).decode('utf-8')
        postgres_secret = kube_v1.read_namespaced_secret(
            name=build_name + '-postgresql', namespace=chart_builder.namespace
        )
        if ('postgresql' not in odoo_values.keys()):
            odoo_values['postgresql'] = {}
        odoo_values['postgresql']['postgresqlPassword'] = base64.standard_b64decode(
            postgres_secret.data['postgresql-password']
        ).decode('utf-8')

        chart_builder = define_chart_builder(chart_builder.namespace, build_name, odoo_values, app_version)
        chart_builder.upgrade_chart(options={'atomic': None, 'dependency-update': None})
        return 1
    else:
        print('Build not found')
        return 0


def odoo_value_overrides(build: BuildParam, upgrade: bool=False):
    try:
        tls_key = open('config/' + deployment_mode + '/ssl-key', 'r')
        tls_key_data = tls_key.read()
        tls_key.close()
        tls_cert = open('config/' + deployment_mode + '/ssl-cert', 'r')
        tls_cert_data = tls_cert.read()
        tls_cert.close()
    except FileNotFoundError:
        print('ERROR: Setup tls key and certificate files -- See README.md')
        exit(0)

    odoo_values = {
        'image': {
            'registry': build.app_registry,
            'repository': build.app_repository,
            'tag': build.app_version,
            'pullPolicy': 'Always'
        },
        'odooUsername': build.odoo_username,
        'odooEmail': build.odoo_username,
        'service': {'type': 'ClusterIP'},
        'ingress': {
            'enabled': 'true',
            'hostname': build.build_domain,
            'tls': 'true',
            'secrets': [
                {
                    'name': build.build_domain + '-tls',
                    'key': tls_key_data.encode('ascii'),
                    'certificate': tls_cert_data.encode('ascii')
                }
            ]
        },
        'affinity': {
            'podAffinity': {
                'requiredDuringSchedulingIgnoredDuringExecution': [
                    {
                        'labelSelector': {
                            'matchExpressions': [
                                {
                                    'key': 'app.kubernetes.io/instance',
                                    'operator': 'In',
                                    'values': [build.build_name]
                                }
                            ]
                        },
                        'topologyKey': 'kubernetes.io/hostname'
                    }
                ]
            }
        },
        'resources': {
            'requests': {
                'memory': '512Mi',
                'cpu': '250m',
            },
            'limits': {
                'memory': build.max_memory,
                'cpu': build.max_cpu,
            },
        },
    }

    if (build.storage_class):
        odoo_values['persistence'] = {
            'storageClass': build.storage_class
        }
        odoo_values['postgresql'] = {
            'persistence': {
                'storageClass': build.storage_class
            }
        }

    if (build.smtp_host):
        odoo_values['smtpHost'] = build.smtp_host
        odoo_values['smtpPort'] = build.smtp_port
        odoo_values['smtpUser'] = build.smtp_user
        odoo_values['smtpPassword'] = build.smtp_password
        odoo_values['smtpProtocol'] = build.smtp_protocol

    return odoo_values


def run_command_in_pod(namespace, pod_name, command):
    kubeconfig()
    kube_v1 = client.CoreV1Api()
    pod_result = kube_v1.list_namespaced_pod(namespace=namespace, label_selector='app.kubernetes.io/name=' + pod_name)
    for pod in pod_result.items:
        resp = stream(kube_v1.connect_get_namespaced_pod_exec, pod.metadata.name, namespace,
            command=['/bin/sh', '-c', command],
            stderr=True, stdin=False,
            stdout=True, tty=False)
        print(resp)
        return resp.strip() # TODO: run in all pods


def get_pod_status(namespace, pod_name):
    kubeconfig()
    kube_v1 = client.CoreV1Api()
    pod_result = kube_v1.list_namespaced_pod(namespace=namespace, label_selector='app.kubernetes.io/name=' + pod_name)
    for pod in pod_result.items:
        return pod.status.phase.lower() # TODO: run in all pods


def run_command_in_odoo_pod(namespace, command):
    return run_command_in_pod(namespace, 'odoo', command)


def run_command_in_postgresql_pod(namespace, command):
    return run_command_in_pod(namespace, 'postgresql', command)


def get_build_status(build_name: str, namespace: str):
    kubeconfig()
    helm_installations = get_helm_installations(namespace)
    try:
        if helm_installations:
            index = helm_installations['NAME'].index(build_name)
            return helm_installations['STATUS'][index]
    except ValueError as e:
        return False


def get_odoo_status(namespace):
    response = run_command_in_odoo_pod(namespace, 'nami status odoo')
    if 'not fully installed' in response:
        return 'not installed'
    elif 'ERROR' in response:
        return 'error'
    else:
        return response.split().pop().lower()


def get_postgresql_status(namespace):
    response = run_command_in_postgresql_pod(namespace, 'pg_isready -U postgres -h 127.0.0.1 -p 5432')
    if 'accepting connections' in response:
        return 'running'
    else:
        return 'not ready'


def restart_odoo(namespace, install='', update=''):
    response = run_command_in_odoo_pod(namespace, 'nami stop odoo')
    response += run_command_in_odoo_pod(namespace, 'chmod -R 777 /opt/bitnami/odoo/data/')
    response += run_command_in_odoo_pod(
        namespace, 
        '/opt/bitnami/odoo/venv/bin/python ' +
        '/opt/bitnami/odoo/openerp-server ' +
        '--config \'/opt/bitnami/odoo/openerp-server.conf\' ' +
        '--stop-after-init ' +
        (('-i ' + install + ' ') if install != '' else '') +
        (('-u ' + update + ' ') if update != '' else '')
    )
    response += run_command_in_odoo_pod(namespace, 'chmod -R 777 /opt/bitnami/odoo/data/')
    response += run_command_in_odoo_pod(namespace, 'nami start odoo')
    print('Restart Odoo: ' + response)


# Main
def main(argv):
    deployment_mode = 'development'
    try:
        opts, args = getopt.getopt(argv,'hm:',['mode='])
    except getopt.GetoptError:
        print('build.py -m <development|production|...>')
        sys.exit(2)
    
    for opt, arg in opts:
        if opt == '-h':
            print('build.py -m <development|production|...>')
            sys.exit()
        elif opt in ('-m', '--mode'):
            deployment_mode = arg

    print('Deployment mode:', deployment_mode)

    try:
        build_params_file = open('config/' + deployment_mode + '/build-params.json', 'r')
        build_params = json.loads(build_params_file.read())
        build_params_file.close()
    except FileNotFoundError:
        print('ERROR: Setup build params JSON file -- See README.md')
        exit(0)

    build = BuildParam(**build_params)
    odoo_values = odoo_value_overrides(build)
    chart_builder = define_chart_builder(build.namespace, build.build_name, odoo_values, build.app_version)

    kubeconfig()
    if chart_builder.is_installed:
        build_upgrade(chart_builder, build.build_name, odoo_values, build.app_version)
    else:
        build_initial(chart_builder)


if __name__ == '__main__':
    main(sys.argv[1:])