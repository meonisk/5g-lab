"""Логические AS одного процесса SIP AS.

Модуль услуги объявляет HOST — имя логического AS до ``.<IMS_DOMAIN>`` (из него
S-CSCF строит Route по iFC) — и handle(message, peer) для запросов с этим Route.
Услуга-B2BUA (translate) реализует on_invite(message, peer), on_answer(call,
response) -> bool и on_bye(call); услуга-прокси (record) — on_invite(message, peer),
on_answer(response) и on_bye(message, peer). Транзакции, Via, Route, ответы и
освобождение MRF делает core.
"""
