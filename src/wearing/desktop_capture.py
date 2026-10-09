"""Retain native read-only AX text from the same pinned driver's capture.

Upstream's action-oriented element list omits static text and editable values.
Keep the original capture transport and sticky target; do not make a second
driver request that could change the element snapshot used for approval.
"""
import json


def capture_with_text(args, handler, backend_for_call, tree_and_title, session):
    if args.get('action')!='capture':return handler(args,session_id=session)
    text=None
    with backend_for_call(session_id=session) as backend:
        fetch=getattr(backend,'_fetch_or_refetch',None)
        if fetch is None:return handler(args,session_id=session)
        had_local='_fetch_or_refetch' in vars(backend)
        def retaining(*values,**options):
            nonlocal text
            out=fetch(*values,**options)
            if values and values[0]=='get_window_state' and not out.get('isError'):
                tree,_=tree_and_title(out)
                if isinstance(tree,str):text=tree[:65536]
            return out
        backend._fetch_or_refetch=retaining
        try:result=handler(args,session_id=session)
        finally:
            if had_local:backend._fetch_or_refetch=fetch
            else:del backend._fetch_or_refetch
    if text and isinstance(result,str):
        value=json.loads(result)
        if not value.get('error') and value.get('ok') is not False:
            value['accessibility_text']=text
            return json.dumps(value,ensure_ascii=False)
    return result
