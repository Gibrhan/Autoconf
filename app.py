from flask import Flask, render_template, request, jsonify, session
import yaml
import subprocess
import platform
import threading
import time
import re
import json
from datetime import datetime
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException

app = Flask(__name__)
app.secret_key = 'cisco_router_management_2024_secure_key'

# Cargar dispositivos desde el archivo YAML
def load_devices():
    try:
        with open('devices.yaml', 'r') as file:
            data = yaml.safe_load(file)
            return data['devices']
    except FileNotFoundError:
        print("Error: No se encontró el archivo devices.yaml")
        return []
    except yaml.YAMLError as e:
        print(f"Error al leer el archivo YAML: {e}")
        return []

# Usuarios predefinidos
USERS = {
    'admin': {'password': 'admin123', 'role': 'admin'},
    'user': {'password': 'user123', 'role': 'user'}
}

# ============================================================================
# FUNCIONES DE CONECTIVIDAD Y UTILIDADES
# ============================================================================

def connect_to_device(device_info):
    """
    Establece conexión SSH con un dispositivo usando Netmiko
    """
    try:
        connection = ConnectHandler(
            device_type=device_info['device_type'],
            host=device_info['host'],
            username=device_info['username'],
            password=device_info['password'],
            secret=device_info.get('secret', ''),
            timeout=10
        )
        return connection, None
    except NetmikoTimeoutException:
        return None, "Timeout - No se pudo conectar al dispositivo"
    except NetmikoAuthenticationException:
        return None, "Error de autenticación"
    except Exception as e:
        return None, f"Error de conexión: {str(e)}"

def ping_device(host):
    """
    Realiza ping a un dispositivo y retorna el resultado
    """
    try:
        if platform.system().lower() == 'windows':
            cmd = ['ping', '-n', '4', host]
        else:
            cmd = ['ping', '-c', '4', host]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            return {
                'status': 'success',
                'message': 'Dispositivo alcanzable',
                'output': result.stdout,
                'response_time': extract_response_time(result.stdout)
            }
        else:
            return {
                'status': 'error',
                'message': 'Dispositivo no alcanzable',
                'output': result.stdout + result.stderr,
                'response_time': None
            }
    except subprocess.TimeoutExpired:
        return {
            'status': 'timeout',
            'message': 'Tiempo de espera agotado',
            'output': 'El ping excedió el tiempo límite de 10 segundos',
            'response_time': None
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Error al ejecutar ping: {str(e)}',
            'output': '',
            'response_time': None
        }

def extract_response_time(ping_output):
    """
    Extrae el tiempo de respuesta promedio del output del ping
    """
    lines = ping_output.split('\n')
    for line in lines:
        if 'time=' in line or 'tiempo=' in line:
            time_match = re.search(r'time[=<]\s*(\d+(?:\.\d+)?)\s*ms', line, re.IGNORECASE)
            if time_match:
                return float(time_match.group(1))
    return None

# ============================================================================
# RUTAS DE AUTENTICACIÓN
# ============================================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if username in USERS and USERS[username]['password'] == password:
        session['username'] = username
        session['role'] = USERS[username]['role']
        return jsonify({
            'success': True,
            'role': USERS[username]['role'],
            'username': username
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Usuario o contraseña incorrectos'
        })

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/check_auth', methods=['GET'])
def check_auth():
    if 'username' in session:
        return jsonify({
            'authenticated': True,
            'username': session['username'],
            'role': session['role']
        })
    else:
        return jsonify({'authenticated': False})

# ============================================================================
# RUTAS DE PING
# ============================================================================

@app.route('/ping', methods=['GET', 'POST'])
def ping_routers():
    if 'username' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    
    devices = load_devices()
    
    if request.method == 'GET':
        device_list = []
        for device in devices:
            device_list.append({
                'name': device['name'],
                'host': device['host'],
                'status': 'unknown'
            })
        return jsonify({'devices': device_list})
    
    elif request.method == 'POST':
        data = request.get_json()
        target = data.get('target', 'all')
        
        results = []
        
        if target == 'all':
            for device in devices:
                print(f"Haciendo ping a {device['name']} ({device['host']})...")
                result = ping_device(device['host'])
                results.append({
                    'name': device['name'],
                    'host': device['host'],
                    'result': result,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
        else:
            device = next((d for d in devices if d['name'] == target), None)
            if device:
                print(f"Haciendo ping a {device['name']} ({device['host']})...")
                result = ping_device(device['host'])
                results.append({
                    'name': device['name'],
                    'host': device['host'],
                    'result': result,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            else:
                return jsonify({'error': 'Dispositivo no encontrado'}), 404
        
        return jsonify({'results': results})

# ============================================================================
# RUTAS DE MONITOREO
# ============================================================================

@app.route('/monitoring/config', methods=['POST'])
def get_device_config():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500
    
    try:
        output = connection.send_command('show running-config')
        connection.disconnect()
        
        return jsonify({
            'success': True,
            'device': device_name,
            'config': output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al obtener configuración: {str(e)}'}), 500

@app.route('/monitoring/interfaces', methods=['POST'])
def get_interfaces():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500
    
    try:
        output = connection.send_command('show ip interface brief')
        connection.disconnect()
        
        return jsonify({
            'success': True,
            'device': device_name,
            'interfaces': output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al obtener interfaces: {str(e)}'}), 500

@app.route('/monitoring/cdp', methods=['POST'])
def get_cdp_neighbors():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500
    
    try:
        output = connection.send_command('show cdp neighbors detail')
        connection.disconnect()
        
        return jsonify({
            'success': True,
            'device': device_name,
            'cdp_neighbors': output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al obtener vecinos CDP: {str(e)}'}), 500

@app.route('/monitoring/traffic', methods=['POST'])
def get_interface_traffic():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500
    
    try:
        output = connection.send_command('show interfaces')
        connection.disconnect()
        
        return jsonify({
            'success': True,
            'device': device_name,
            'traffic_info': output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al obtener tráfico: {str(e)}'}), 500

# ============================================================================
# RUTAS DE MANTENIMIENTO
# ============================================================================

@app.route('/maintenance/patch_simulation', methods=['POST'])
def simulate_patch():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    # Simulación de aplicación de parches
    simulation_steps = [
        "Verificando versión actual del sistema...",
        "Descargando archivo de parche...",
        "Verificando integridad del archivo...",
        "Creando respaldo de configuración...",
        "Aplicando parche de seguridad...",
        "Reiniciando servicios...",
        "Verificando funcionamiento...",
        "Parche aplicado exitosamente"
    ]
    
    return jsonify({
        'success': True,
        'device': device_name,
        'simulation_steps': simulation_steps,
        'status': 'completed',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/maintenance/apply_template', methods=['POST'])
def apply_yaml_template():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    template_content = data.get('template_content')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    try:
        # Parsear el contenido YAML
        yaml_data = yaml.safe_load(template_content)
        
        # Validar estructura básica
        if 'commands' not in yaml_data:
            return jsonify({'error': 'Template debe contener una sección "commands"'}), 400
        
        connection, error = connect_to_device(device)
        if error:
            return jsonify({'error': error}), 500
        
        # Aplicar comandos del template
        results = []
        for command in yaml_data['commands']:
            try:
                if command.startswith('configure'):
                    connection.enable()
                    output = connection.send_command(command)
                else:
                    output = connection.send_command(command)
                
                results.append({
                    'command': command,
                    'output': output,
                    'status': 'success'
                })
            except Exception as cmd_error:
                results.append({
                    'command': command,
                    'output': str(cmd_error),
                    'status': 'error'
                })
        
        connection.disconnect()
        
        return jsonify({
            'success': True,
            'device': device_name,
            'results': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except yaml.YAMLError as e:
        return jsonify({'error': f'Error en formato YAML: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Error al aplicar template: {str(e)}'}), 500

# ============================================================================
# RUTAS DE SEGURIDAD
# ============================================================================

@app.route('/security/change_password', methods=['POST'])
def change_device_password():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    
    data = request.get_json()
    device_name = data.get('device_name')
    new_password = data.get('new_password')
    username_to_change = data.get('username_to_change', 'admin')
    
    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)
    
    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404
    
    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500
    
    try:
        connection.enable()
        
        # Comandos para cambiar contraseña
        config_commands = [
            'configure terminal',
            f'username {username_to_change} password {new_password}',
            'exit'
        ]
        
        output = connection.send_config_set(config_commands)
        
        # Guardar configuración
        save_output = connection.send_command('write memory')
        
        connection.disconnect()
        
        return jsonify({
            'success': True,
            'device': device_name,
            'message': f'Contraseña cambiada exitosamente para usuario {username_to_change}',
            'output': output,
            'save_output': save_output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al cambiar contraseña: {str(e)}'}), 500

# ============================================================================
# RUTAS ADICIONALES DE MANTENIMIENTO
# ============================================================================

@app.route('/maintenance/backup', methods=['POST'])
def maintenance_backup():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403
    data = request.get_json()
    device_name = data.get('device_name')

    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)

    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404

    try:
        connection, error = connect_to_device(device)
        if error:
            return jsonify({'error': error}), 500

        connection.enable()
        # Simulamos backup (en un caso real sería copy running-config tftp:)
        output = connection.send_command('show running-config')
        connection.disconnect()

        # Aquí podrías guardar el backup a un archivo si quieres
        filename = f"/backups_routers/backup_{device_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
        with open(filename, 'w') as f:
            f.write(output)

        return jsonify({
            'success': True,
            'message': f'Backup realizado correctamente y guardado como {filename}',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({'error': f'Error al realizar backup: {str(e)}'}), 500


# ============================================================================
# RUTAS ADICIONALES DE SEGURIDAD
# ============================================================================

@app.route('/security/manage_users', methods=['POST'])
def manage_users():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    data = request.get_json()
    device_name = data.get('device_name')
    user_action = data.get('action')  # add / remove
    username = data.get('username')
    password = data.get('password', '')

    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)

    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404

    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500

    try:
        connection.enable()
        if user_action == 'add':
            config_cmds = [
                'configure terminal',
                f'username {username} privilege 15 password {password}',
                'exit'
            ]
            message = f'Usuario {username} agregado correctamente'
        elif user_action == 'remove':
            config_cmds = [
                'configure terminal',
                f'no username {username}',
                'exit'
            ]
            message = f'Usuario {username} eliminado correctamente'
        else:
            return jsonify({'error': 'Acción no válida'}), 400

        output = connection.send_config_set(config_cmds)
        connection.disconnect()

        return jsonify({
            'success': True,
            'message': message,
            'output': output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al gestionar usuarios: {str(e)}'}), 500


@app.route('/security/configure_acls', methods=['POST'])
def configure_acls():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    data = request.get_json()
    device_name = data.get('device_name')
    acl_commands = data.get('acl_commands', [])

    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)

    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404

    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500

    try:
        connection.enable()
        output = connection.send_config_set(acl_commands)
        connection.disconnect()

        return jsonify({
            'success': True,
            'message': 'ACLs configuradas correctamente',
            'output': output,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al configurar ACLs: {str(e)}'}), 500


@app.route('/security/audit', methods=['POST'])
def security_audit():
    if 'username' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Acceso denegado'}), 403

    data = request.get_json()
    device_name = data.get('device_name')

    devices = load_devices()
    device = next((d for d in devices if d['name'] == device_name), None)

    if not device:
        return jsonify({'error': 'Dispositivo no encontrado'}), 404

    connection, error = connect_to_device(device)
    if error:
        return jsonify({'error': error}), 500

    try:
        connection.enable()
        audit_commands = [
            'show running-config',
            'show users',
            'show privilege'
        ]
        audit_results = {}
        for cmd in audit_commands:
            audit_results[cmd] = connection.send_command(cmd)

        connection.disconnect()

        return jsonify({
            'success': True,
            'message': 'Auditoría de seguridad realizada',
            'results': audit_results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        connection.disconnect()
        return jsonify({'error': f'Error al realizar auditoría: {str(e)}'}), 500


# ============================================================================
# RUTAS GENERALES
# ============================================================================

@app.route('/devices', methods=['GET'])
def get_devices():
    if 'username' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    
    devices = load_devices()
    device_list = []
    
    for device in devices:
        device_list.append({
            'name': device['name'],
            'host': device['host'],
            'device_type': device['device_type']
        })
    
    return jsonify({'devices': device_list})

# ============================================================================
# INICIALIZACIÓN DE LA APLICACIÓN
# ============================================================================

if __name__ == '__main__':
    print("=" * 50)
    print("🔧 CISCO ROUTER MANAGEMENT SYSTEM")
    print("=" * 50)
    print("🌐 Iniciando servidor Flask...")
    print(f"📋 Dispositivos cargados: {len(load_devices())}")
    print("🔑 Usuarios disponibles:")
    print("   - admin / admin123 (Administrador)")
    print("   - user / user123 (Usuario básico)")
    print("🌍 Accede a: http://localhost:5000")
    print("=" * 50)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
