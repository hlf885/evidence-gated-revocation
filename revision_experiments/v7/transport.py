"""Serialized localhost RPC transport for the isolated Unity controller."""
import json, queue, socket, threading, time, uuid

class UnityRPC:
    def __init__(self, command_port=5505, response_port=5506):
        self.command_port=command_port
        self.inbox=queue.Queue()
        self.server=socket.socket(); self.server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.server.bind(('127.0.0.1',response_port)); self.server.listen(); self.server.settimeout(.3)
        self.closed=False
        self.thread=threading.Thread(target=self._listen,daemon=True); self.thread.start()

    def _listen(self):
        while not self.closed:
            try: client,_=self.server.accept()
            except socket.timeout: continue
            except OSError: break
            try:
                with client:
                    client.settimeout(10); chunks=[]; size=0
                    while True:
                        data=client.recv(65536)
                        if not data:break
                        size+=len(data)
                        if size>32_000_000:raise ValueError('Oversized response')
                        chunks.append(data)
                raw=b''.join(chunks).decode('utf-8')
                if raw.startswith('REVISION:'):
                    self.inbox.put(json.loads(raw[len('REVISION:'):]))
            except Exception as exc:
                self.inbox.put({'transport_error':type(exc).__name__})

    def call(self,verb,trial_id='',timeout=30,**payload):
        request_id=uuid.uuid4().hex
        data=(verb+':'+json.dumps({'requestId':request_id,'trialId':trial_id,**payload},ensure_ascii=True)).encode()
        if len(data)>65536:raise ValueError('Oversized command')
        with socket.create_connection(('127.0.0.1',self.command_port),timeout=min(timeout,5)) as client:
            client.sendall(data);client.shutdown(socket.SHUT_WR)
        deadline=time.monotonic()+timeout
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Unity RPC timeout: '+verb)
            try: response=self.inbox.get(timeout=remaining)
            except queue.Empty:raise TimeoutError('Unity RPC timeout: '+verb)
            if response.get('requestId')!=request_id:continue
            if not response.get('ok'):raise RuntimeError('Unity rejected '+verb+': '+response.get('error',''))
            return response

    def close(self):
        self.closed=True;self.server.close();self.thread.join(timeout=1)
