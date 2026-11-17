begin;
create or replace function public.crm_record_suggestion_review(p_suggestion uuid,p_reviewer uuid,p_action text,p_reason text,p_note text,p_final jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare s public.crm_followups%rowtype; r public.crm_reviewers%rowtype; result_id uuid; final_value jsonb;
begin
 if not coalesce(public.crm_authorized(),false) then raise exception 'Unauthorized'; end if;
 select * into r from public.crm_reviewers where id=p_reviewer and active;
 if not found then return jsonb_build_object('error','Sign in as an active reviewer.'); end if;
 select * into s from public.crm_followups where id=p_suggestion for update;
 if not found or s.status<>'pending' then return jsonb_build_object('error','Suggestion is no longer pending.'); end if;
 if p_action not in ('approve','reject','edit_approve') or (p_action in ('reject','edit_approve') and p_reason is null) then return jsonb_build_object('error','Select an action and required reason.'); end if;
 if s.original_suggestion is null then return jsonb_build_object('error','Original suggestion is missing.'); end if;
 if p_action='edit_approve' and (p_final is null or p_final=s.original_suggestion) then return jsonb_build_object('error','Edit the suggestion before approving.'); end if;
 if p_action<>'reject' and (s.guardrail_result is null or s.guardrail_result->>'policy_version'<>'crm-guardrails-v1' or not coalesce((s.guardrail_result->>'can_approve')::boolean,false)) then return jsonb_build_object('error','Required linked information must be verified before approving. Correct the source and run the guardrail check.'); end if;
 final_value=case when p_action='reject' then null when p_action='approve' then s.guardrail_result->'safe_suggestion' else p_final end;
 insert into public.crm_suggestion_reviews(suggestion_id,action,reason,note,original_suggestion,final_suggestion,workflow,context,reviewer_id,reviewer_name,team,model,prompt_version_id,prompt_label,response_time_ms,estimated_cost_usd,cost_source)
 values(s.id,p_action,p_reason,coalesce(p_note,''),s.original_suggestion,final_value,s.workflow_type,s.context || jsonb_build_object('entity_type',s.entity_type,'entity_id',s.entity_id,'customer_id',case when s.entity_type='contacts' then s.entity_id else (select contact_id from public.crm_deals where id=s.entity_id) end,'opportunity_id',case when s.entity_type='deals' then s.entity_id else null end,'assigned_team',s.team),r.id,r.display_name,r.team,s.model,s.prompt_version_id,s.prompt_label,s.response_time_ms,s.estimated_cost_usd,s.cost_source) returning id into result_id;
 perform set_config('app.review_transaction','on',true);
 update public.crm_followups set status=case when p_action='reject' then 'rejected' else 'approved' end,final_suggestion=final_value,reviewed_at=now(),review_note=coalesce(p_note,'') where id=s.id;
 insert into public.crm_guardrail_events(suggestion_id,review_id,source,guardrail,policy_version,model_input,proposed_output,safe_output,proposed_action,verdict,status,reason,final_action,enforced,passed,external_changes)
 values(s.id,result_id,'production','No automatic external actions','crm-guardrails-v1',coalesce(s.guardrail_result->'original_model_input',s.context),s.original_suggestion,coalesce(final_value,'{}'::jsonb),'record_human_review','allowed','Draft only','A named human reviewed content. This does not authorize email sending, external creation, or deletion.','Human review saved; no external action performed.',true,true,0);
 return jsonb_build_object('review_id',result_id,'message','Review saved. No message sent and no meeting changes applied.');
end $$;

create or replace function public.crm_release_prompt(p_version uuid,p_batch uuid,p_reviewer uuid,p_agent_version text,p_model text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v public.crm_prompt_versions%rowtype; b public.crm_prompt_evaluation_batches%rowtype; count_runs integer; count_checks integer; count_guards integer;
begin
 if not coalesce(public.crm_authorized(),false) then raise exception 'Unauthorized'; end if;
 if not exists(select 1 from public.crm_reviewers where id=p_reviewer and active and role='admin') then return jsonb_build_object('error','An active administrator must release prompts.'); end if;
 select * into v from public.crm_prompt_versions where id=p_version for update;
 if not found or v.status<>'approved' or v.approved_by is null then return jsonb_build_object('error','Human approval is required before release.'); end if;
 select * into b from public.crm_prompt_evaluation_batches where id=p_batch and prompt_version_id=p_version;
 if not found or b.status<>'passed' or b.created_at<v.approved_at or b.agent_version<>p_agent_version or b.model<>p_model or b.gate_version<>'crm-quality-v1' then return jsonb_build_object('error','A passing evaluation suite for this approved version, current code, and model is required.'); end if;
 select count(*) into count_runs from public.crm_evaluation_runs er join public.crm_evaluation_scenarios s on s.id=er.scenario_id
 where er.batch_id=p_batch and er.prompt_version_id=v.id and er.prompt_hash=v.content_hash and er.agent_version=p_agent_version and er.requested_model=p_model and er.status='passed' and s.scenario_number in (1,5,7);
 if count_runs<>3 then return jsonb_build_object('error','All three evaluation scenarios must pass.'); end if;
 with required(scenario_number,rule_key,expected) as (values (1,'draft_count','1'::jsonb),
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
 select count(*) into count_checks from required n join public.crm_evaluation_scenarios s on s.scenario_number=n.scenario_number
 join public.crm_evaluation_runs er on er.scenario_id=s.id and er.batch_id=p_batch
 join public.crm_evaluation_check_results cr on cr.run_id=er.id and cr.rule_key=n.rule_key
 where cr.passed and cr.expected=n.expected and cr.actual->'value'=n.expected;
 if count_checks<>17 then return jsonb_build_object('error','All 17 canonical business checks must pass; edited dashboard expectations cannot weaken the release gate.'); end if;
 select count(distinct g.case_id) into count_guards from public.crm_guardrail_test_runs g join public.crm_guardrail_events e on e.id=g.event_id where g.batch_id=p_batch and g.agent_version=p_agent_version and g.policy_version='crm-guardrails-v1' and g.passed and e.enforced and e.passed and e.external_changes=0;
 if count_guards<>8 then return jsonb_build_object('error','All eight server-enforced guardrail evaluations must pass before release.'); end if;
 perform pg_advisory_xact_lock(hashtext('crm-prompt-release-'||v.workflow));
 perform set_config('app.prompt_release','on',true);
 update public.crm_prompt_versions set status='retired' where workflow=v.workflow and status='active';
 update public.crm_prompt_versions set status='active',released_by=p_reviewer,released_at=now() where id=v.id;
 return jsonb_build_object('released',true,'version',v.version,'workflow',v.workflow);
end $$;

commit;
