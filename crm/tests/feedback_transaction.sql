-- Database integration test: all rows, authorization stub and prompt releases roll back.
begin;
create or replace function public.crm_authorized() returns boolean language sql stable set search_path='' as $$ select true $$;
do $test$
declare reviewer_id uuid; suggestion_id uuid; candidate_id uuid; batch_id uuid; result jsonb; original jsonb; v integer;
begin
 insert into public.crm_reviewers(username,display_name,team,password_hash,role) values ('rollback-'||gen_random_uuid()::text,'Transactional test reviewer','Test team','not-a-login-hash','admin') returning id into reviewer_id;
 original=jsonb_build_object('subject','Synthetic test','body','Original AI proposal','next_action','Review proposal');
 insert into public.crm_followups(entity_type,entity_id,activity_version,context,model,status,subject,body,next_action,original_suggestion)
 values('contacts',gen_random_uuid(),'rollback-test-'||gen_random_uuid()::text,'{"record":{"name":"Synthetic test"}}','test-model','pending','Synthetic test','Original AI proposal','Review proposal',original) returning id into suggestion_id;
 update public.crm_followups set guardrail_result=jsonb_build_object('policy_version','crm-guardrails-v1','can_approve',true,'safe_suggestion',original,'model_input','{}'::jsonb) where id=suggestion_id;
 result=public.crm_record_suggestion_review(suggestion_id,reviewer_id,'edit_approve','Incorrect tone','Test note',jsonb_build_object('subject','Synthetic test','body','Human-reviewed version','next_action','Review proposal'));
 if result->>'review_id' is null then raise exception 'Review transaction failed: %',result; end if;
 if not exists(select 1 from public.crm_suggestion_reviews where crm_suggestion_reviews.suggestion_id=(select id from public.crm_followups where activity_version like 'rollback-test-%' order by created_at desc limit 1) and reviewer_name='Transactional test reviewer' and team='Test team' and original_suggestion=original and final_suggestion->>'body'='Human-reviewed version') then raise exception 'Review evidence missing'; end if;
 result=public.crm_record_suggestion_review(suggestion_id,reviewer_id,'approve',null,'',null);
 if result->>'error' is null then raise exception 'Duplicate review was accepted'; end if;
 select coalesce(max(version),0)+1 into v from public.crm_prompt_versions where workflow='followup';
 insert into public.crm_prompt_versions(workflow,version,system_prompt,status,rationale,created_by) values('followup',v,'Temporary rollback-only prompt','draft','Transaction test',reviewer_id) returning id into candidate_id;
 result=public.crm_release_prompt(candidate_id,gen_random_uuid(),reviewer_id,'test-code','test-model');
 if result->>'error' is null then raise exception 'Unapproved prompt released'; end if;
 update public.crm_prompt_versions set status='approved',approved_by=reviewer_id,approved_at=now() where id=candidate_id;
 insert into public.crm_prompt_evaluation_batches(prompt_version_id,created_by,agent_version,model,status) values(candidate_id,reviewer_id,'test-code','test-model','passed') returning id into batch_id;
 result=public.crm_release_prompt(candidate_id,batch_id,reviewer_id,'test-code','test-model');
 if result->>'error' is null then raise exception 'Empty evaluation batch released'; end if;
 insert into public.crm_evaluation_runs(batch_id,scenario_id,status,input_snapshot,expected_behavior,rules_snapshot,model,requested_model,agent_version,prompt_version_id,prompt_hash)
 select batch_id,s.id,'passed','{}','[]','[]','test-model','test-model','test-code',candidate_id,p.content_hash from public.crm_evaluation_scenarios s cross join public.crm_prompt_versions p where p.id=candidate_id;
 result=public.crm_release_prompt(candidate_id,batch_id,reviewer_id,'test-code','test-model');
 if result->>'error' is null then raise exception 'Missing canonical checks released'; end if;
 with needed(number,rule_key,expected) as (values (1,'draft_count','1'::jsonb),
(1,'sent_count','0'::jsonb),
(1,'correct_context','true'::jsonb),
(1,'personalized_reference','true'::jsonb),
(1,'owner_routing','true'::jsonb),
(1,'no_duplicate_action','true'::jsonb),
(5,'draft_count','0'::jsonb),
(5,'no_invented_contact','true'::jsonb),
(5,'missing_email_recorded','true'::jsonb),
(5,'safe_next_action','true'::jsonb),
(5,'sent_count','0'::jsonb),
(7,'exact_due_date','"2026-11-21"'::jsonb),
(7,'task_owner','"Priya"'::jsonb),
(7,'task_association','true'::jsonb),
(7,'source_evidence','true'::jsonb),
(7,'no_unsupported_commitment','true'::jsonb),
(7,'sent_count','0'::jsonb))
 insert into public.crm_evaluation_check_results(run_id,rule_id,rule_key,name,passed,expected,actual,explanation)
 select er.id,r.id,n.rule_key,r.name,true,n.expected,jsonb_build_object('value',n.expected),'Rollback-only positive gate test' from needed n join public.crm_evaluation_scenarios s on s.scenario_number=n.number join public.crm_evaluation_rules r on r.scenario_id=s.id and r.rule_key=n.rule_key join public.crm_evaluation_runs er on er.scenario_id=s.id and er.batch_id=(select b.id from public.crm_prompt_evaluation_batches b where b.prompt_version_id=candidate_id);
 insert into public.crm_guardrail_events(test_case_id,source,guardrail,policy_version,model_input,proposed_output,safe_output,proposed_action,verdict,status,reason,final_action,enforced,passed,external_changes)
 select c.id,'evaluation',c.expected_behavior->>'guardrail','crm-guardrails-v1',c.input_context,c.proposed_output,'{}','test','blocked','Blocked','Rollback-only test','No external change',true,true,0 from public.crm_guardrail_test_cases c;
 insert into public.crm_guardrail_test_runs(case_id,event_id,batch_id,input_context,proposed_output,expected_behavior,actual_behavior,guardrail,passed,response_time_ms,agent_version,policy_version)
 select c.id,e.id,batch_id,c.input_context,c.proposed_output,c.expected_behavior,'{}',c.expected_behavior->>'guardrail',true,0,'test-code','crm-guardrails-v1' from public.crm_guardrail_test_cases c join public.crm_guardrail_events e on e.test_case_id=c.id where e.reason='Rollback-only test';
 result=public.crm_release_prompt(candidate_id,batch_id,reviewer_id,'test-code','test-model');
 if result->>'released'<>'true' then raise exception 'Complete positive gate rejected: %',result; end if;
end $test$;
rollback;
