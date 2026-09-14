from __future__ import annotations
import json, tempfile
from pathlib import Path
from typing import Any
from herzchen.authoring import AuthoringLifecycle
from herzchen.authoring.sessions import AuthoringSessionService, register_authoring
from herzchen.content import ContentCommandHandler
from herzchen.content.model import domain_contribution as content_contribution
from herzchen.content.packets import domain_contribution as packet_contribution
from herzchen.contracts import AuthenticatedActor
from herzchen.domains.work import WorkGraph
from herzchen.domains.work.batches import ProjectBatches
from herzchen.domains.work.decisions import DecisionsModule
from herzchen.domains.work.sheet import ProjectSheet
from herzchen.kernel import Store
from herzchen.packs.templates import TemplateEngine, blank_project_template

def safe(v: Any) -> Any:
    if hasattr(v, 'to_dict'): return v.to_dict()
    if isinstance(v, dict): return {str(k): safe(x) for k,x in v.items()}
    if isinstance(v, (list,tuple)): return [safe(x) for x in v]
    if isinstance(v, (str,int,float,bool)) or v is None: return v
    return repr(v)

def main() -> None:
    root=Path(tempfile.mkdtemp(prefix='int03-c38-')); store=Store.create(root/'foundation.sqlite',authority='int03-c38')
    actor=AuthenticatedActor('int03-c38','curator','credential'); graph=WorkGraph(store,actor=actor); graph.register(); store.register_domain_handler((content_contribution(), packet_contribution())); register_authoring(store)
    batches=ProjectBatches(store,actor=actor); sheet=ProjectSheet(store,actor=actor,batches=batches); decisions=DecisionsModule(store,actor=actor)
    checks={}; details={}
    try:
        created=batches.create_pending_project(title='',outcome='',curator='curator-1',creator='creator-1',metadata={'why_pending':'awaiting scope','revisit':'when source changes'},logical_request_key='c38-create')
        project=graph.get(created.project.ref); receipt=store.get_receipt('c38-create')
        checks['create_durable_receipt']=receipt is not None and project.lifecycle.value=='pending' and project.payload.get('tasks')==[]
        details['create_durable_receipt']={'project':safe(project.ref),'receipt':safe(receipt),'payload':safe(project.payload)}
        before=len(store.list_events()); replay=batches.create_pending_project(title='',outcome='',curator='curator-1',creator='creator-1',metadata={'why_pending':'awaiting scope','revisit':'when source changes'},logical_request_key='c38-create'); after=len(store.list_events()); err=None
        try: batches.create_pending_project(title='changed',logical_request_key='c38-create')
        except Exception as exc: err={'type':type(exc).__name__,'message':str(exc)}
        checks['replay_and_invalid_create']=replay.project.ref==project.ref and before==after and err is not None; details['replay_and_invalid_create']={'same_ref':safe(replay.project.ref),'events_before':before,'events_after':after,'changed_request_error':err}
        edited=sheet.apply(project,{'approach':'scope remains pending until evidence arrives','metadata':{'why_pending':'awaiting source owner','revisit':'on source revision'},'document_changes':[{'document':'initial-spec','revision':'spec-1','content':{'title':'Initial specification','status':'pending'},'scope':project.id}],'documents':[{'namespace':'work','key':'initial-spec','document_ref':'initial-spec','binding':'pinned','revision':'spec-1'}]},logical_request_key='c38-edit',with_view=True)
        fresh=sheet.export(project); updated=graph.get(project.ref); docs=[safe(x) for x in fresh.documents]
        checks['pending_edit_attach_query']=updated.lifecycle.value=='pending' and updated.payload.get('provenance',{}).get('curator')=='curator-1' and updated.payload.get('metadata',{}).get('why_pending')=='awaiting source owner' and updated.payload.get('metadata',{}).get('revisit')=='on source revision' and len(fresh.tasks)==0 and len(fresh.documents)==1 and docs[0].get('binding',{}).get('mode')=='pinned'; details['pending_edit_attach_query']={'receipt':safe(edited.receipt),'project':safe(updated.payload),'documents':docs}
        project=updated; wait=decisions.record_wait(project,missing_obligation='source scope',owner='curator-1',awaited_ref=project.ref,revisit_condition='when source revision or attention changes',residual_risk={'why':'scope pending'},metadata={'why_pending':'awaiting source owner','curator':'curator-1'},logical_request_key='c38-wait'); readiness=batches.observe_readiness(project,{'ready':True,'cause':'revisit observed'},logical_request_key='c38-ready'); waited=decisions.get_wait(wait.ref); current=graph.get(project.ref)
        checks['revisit_attention_no_dispatch']=waited.revisit_condition=='when source revision or attention changes' and waited.dispatch is False and current.lifecycle.value=='pending' and current.payload.get('readiness',{}).get('dispatch') is False and current.payload.get('admitted') is None; details['revisit_attention_no_dispatch']={'wait':safe(waited),'readiness_ref':safe(readiness),'project':safe(current.payload)}
        admitted=batches.activate_project(project,manager='manager-1',logical_request_key='c38-admit'); checks['explicit_admission_boundary']=admitted.lifecycle.value=='active' and admitted.payload.get('admitted') is True and admitted.payload.get('readiness',{}).get('dispatch') is False; details['explicit_admission_boundary']={'project':safe(admitted.payload),'receipt':safe(store.get_receipt('c38-admit'))}
        engine=TemplateEngine(store,graph=graph,actor=actor); rendered=engine.render(blank_project_template()); blank=engine.instantiate('work.blank_project',logical_request_key='snew-template',actor=actor); blank_record=graph.get(blank.project.ref)
        content=ContentCommandHandler(store); spec_ref=blank.document_refs['initial-specification']; association_ref=blank.association_refs['project:project.documents:specification']; spec_before=content.read(spec_ref); spec_bytes=json.dumps(spec_before['revision']['content'],sort_keys=True,separators=(',',':')).encode(); lifecycle=AuthoringLifecycle(AuthoringSessionService(store)); checkout=root/'blank-checkout'; checkout.mkdir(); (checkout/'project.json').write_bytes(spec_bytes); opened=lifecycle.open(blank.project.ref,actor,request_id='snew-open',target_kind='project-sheet',base_revision=blank_record.revision,initial_content=spec_bytes,pending=True); close=lifecycle.idle_close(opened,request_id='snew-idle-close',checkout_root=checkout,registered_files=['project.json'],handler=batches.lifecycle_handler(blank.project,authoring=lifecycle.service,handle=opened.handle,request_id='snew-domain'),inactivity_seconds=1,last_content_edit=0,now=10,quiesce=lambda:True,writer_check=lambda:True); blank_after=graph.get(blank.project.ref); spec_after=content.read(spec_ref); association=content.read(association_ref)
        checks['built_in_blank_and_untouched_close']=rendered.seed.get('tasks')==[] and blank_record.lifecycle.value=='pending' and len(blank.receipts)==3 and spec_before['document']['role']=='initial-specification' and spec_before['revision']['initial'] is True and spec_before['revision']['parent_revision'] is None and spec_before['revision']['content']['tasks']==[] and spec_before['revision']['content']['metadata']['template_revision']==blank_project_template().revision and association['payload']['active'] is True and blank_after.lifecycle.value=='pending' and blank_after.revision==blank_record.revision and not blank_after.payload.get('tasks') and not (checkout/'project.json').exists() and getattr(close,'status',None)=='closed_cleaned' and spec_after['current_revision']['revision']==spec_before['current_revision']['revision'] and association['payload']['active'] is True and not any(e.event_type=='work.project-sheet.applied' and e.subject.id==blank.project.id for e in store.list_events()); details['built_in_blank_and_untouched_close']={'template':safe(rendered),'project_ref':safe(blank.project.ref),'spec_ref':safe(spec_ref),'association_ref':safe(association_ref),'creation_receipts':[safe(x) for x in blank.receipts],'spec_before':safe(spec_before),'initial_content_bytes':len(spec_bytes),'open':safe(opened),'close':safe(close),'before':safe(blank_record),'after':safe(blank_after),'spec_after':safe(spec_after)}
    finally: store.close()
    print(json.dumps({'schema':'int03-c38-probe-run/v1','overall_ok':all(checks.values()),'checks':checks,'details':details},sort_keys=True,indent=2))
if __name__=='__main__': main()
