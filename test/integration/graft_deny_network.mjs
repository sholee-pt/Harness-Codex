// Test-only guard: a structural retrieval must never reach a model or registry.
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import { syncBuiltinESMExports } from 'node:module';
const deny = () => { throw new Error('Network access attempted by structural retrieval'); };
globalThis.fetch = deny;
http.request = http.get = https.request = https.get = deny;
net.connect = net.createConnection = tls.connect = deny;
syncBuiltinESMExports();
