import { useEffect, useRef, useCallback } from 'react';

interface WSEvent {
  type: string;
  profile_id?: string;
  status?: string;
  error?: string;
  [key: string]: unknown;
}

type EventHandler = (event: WSEvent) => void;

export function useWebSocket(onEvent: EventHandler) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const attempt = useRef(0);
  const debounceMap = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = import.meta.env.VITE_WS_URL || `${protocol}//${window.location.host}`;
    const ws = new WebSocket(`${host}/ws/events`);

    ws.onopen = () => {
      attempt.current = 0;
      console.log('[WS] Connected');
    };

    ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data);
        const key = `${event.type}:${event.profile_id || ''}`;

        // Debounce burst events (150ms per unique key)
        const existing = debounceMap.current.get(key);
        if (existing) clearTimeout(existing);

        debounceMap.current.set(
          key,
          setTimeout(() => {
            debounceMap.current.delete(key);
            handlerRef.current(event);
          }, 150)
        );
      } catch {
        // ignore
      }
    };

    ws.onclose = () => {
      console.log('[WS] Disconnected, reconnecting...');
      const delay = Math.min(1000 * Math.pow(2, attempt.current), 30000);
      attempt.current++;
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      debounceMap.current.forEach((t) => clearTimeout(t));
    };
  }, [connect]);

  // Keep-alive ping every 30s
  useEffect(() => {
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping');
      }
    }, 30000);
    return () => clearInterval(interval);
  }, []);
}
