import socket
import threading
import os
import time

# Configuración
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 5000)) #Busca una variable q represente el nombre de este nodo en la red. Si no, 500 por defecto.
NODE_NAME = os.getenv("NODE_NAME", "nodo") #Busca una variable q represente el nombre de este nodo en la red. Si no, nodo por defecto.
PEERS = os.getenv("PEERS", "").split(",")  # Busca lista de nodos vecinos (host:puerto), la variable PEERS. Si no usa una vacía
                                           # split convierte la cadena en una lista

def handle_client(conn, addr): #atiende al cliente
    data = conn.recv(1024).decode("utf-8") #recibe hasta 1024 bytes de datos, bytes recibidos en texto legible (string) usando codificación UTF-8
    print(f"[{NODE_NAME}] Mensaje recibido de {addr}: {data}") 
    conn.sendall(f"Respuesta de {NODE_NAME}".encode("utf-8")) # asegura al cliente que todos los bytes del mensaje se han enviadp correctamente
    conn.close()

def start_server(): 
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # crea socket del tipo IPV4 y TCP
    server.bind((HOST, PORT)) # direccion y puerto de escucha del servidor
    server.listen() #modo escucha
    print(f"[{NODE_NAME}] Escuchando en {HOST}:{PORT}") #log para indicar q esta activo y donde escucha
    while True: #cada vez que llega un cliente se ejecuta
        conn, addr = server.accept() # el accept devuelve los valores conn(objeto scket) y direccion), es bloqueante hasta que se conecte cliemte
        threading.Thread(target=handle_client, args=(conn, addr)).start() #hilo de ejecucion  para handle_client que recibe, procesa y responde los mensajes (multithreading)

def connect_to_peers():
    while True: #bucle infinito
        for peer in PEERS: #recorre todos los nodos definidos en PEERS
            if not peer.strip(): # devuelve copia string eliminando espacios en blanco del inicio/final
                continue #omitir los huecos vacios
            host, port = peer.split(":") #Divide la cadena del peer en IP (host) y puerto
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s: # Crea un socket TCP temporal (with asegura que se cierre automáticamente al terminar)
                    s.connect((host, int(port))) #Intenta conectarse al peer en (host, port)
                    message = f"Hola desde {NODE_NAME}"
                    s.sendall(message.encode("utf-8"))
                    response = s.recv(1024).decode("utf-8") #Espera a recibir hasta 1024 bytes de respuesta y los convierte a texto
                    print(f"[{NODE_NAME}] Respuesta de {peer}: {response}")
            except Exception as e:
                print(f"[{NODE_NAME}] No se pudo conectar a {peer}: {e}")
        time.sleep(5)  # vuelve a intentar cada 5 segundos

if __name__ == "__main__": #si el archivo actual se está ejecutando directamente
    # Hilo para escuchar
    threading.Thread(target=start_server, daemon=True).start() 
    # Conectar a otros nodos
    connect_to_peers() #esta fuera del hilo porq est afuncion ya tiene un true