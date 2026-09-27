#pragma once
#include "quarry/quarry.hpp"
#include "json.hpp"
namespace quarry {
using nlohmann::json;
inline ExecutionOptions execution_options(const json& options,ExecutionOptions execution) {
    if(!options.is_object()) fail("PROTOCOL","options must be an object");
    for(auto it=options.begin();it!=options.end();++it) {
        if(it.key()=="engine") {
            auto mode=it.value().get<std::string>();
            if(mode!="scalar" && mode!="vector") fail("CLI","engine must be scalar or vector");
            execution.engine=mode=="scalar" ? ExecutionMode::Scalar : ExecutionMode::Vector;
        } else if(it.key()=="build_side") {
            auto side=it.value().get<std::string>();
            if(side!="auto" && side!="left" && side!="right") fail("CLI","build side must be auto, left or right");
            execution.build_side=side=="auto" ? BuildSide::Auto : side=="left" ? BuildSide::Left : BuildSide::Right;
        } else if(it.key()=="batch_size") {
            if(!it.value().is_number_unsigned() && !(it.value().is_number_integer() && it.value().get<std::int64_t>()>0)) fail("CLI","batch size must be a positive integer");
            execution.batch_size=it.value().get<std::size_t>();
            if(execution.batch_size==0 || execution.batch_size>65536) fail("CLI","batch size must be in 1..65536");
        } else if(it.key()=="profile") execution.profile=it.value().get<bool>();
        else if(it.key()=="optimizer" || it.key()=="prune" || it.key()=="pushdown" || it.key()=="fold" || it.key()=="join_reorder") {
            auto value=it.value().get<std::string>();if(value!="on" && value!="off") fail("CLI",it.key()+" must be on or off");
            bool enabled=value=="on";
            if(it.key()=="optimizer") execution.optimizer=enabled;
            else if(it.key()=="prune") execution.prune=enabled;
            else if(it.key()=="pushdown") execution.pushdown=enabled;
            else if(it.key()=="fold") execution.fold=enabled;
            else execution.join_reorder=enabled;
        } else fail("PROTOCOL","unknown execution option: "+it.key());
    }
    return execution;
}
}
