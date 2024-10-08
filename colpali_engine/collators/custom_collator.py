from typing import Optional

from transformers import PreTrainedTokenizer, ProcessorMixin
import torch

class CustomCollator:
    def __init__(
        self,
        processor: Optional[ProcessorMixin] = None,
        tokenizer: Optional[PreTrainedTokenizer] = None,
        max_length: int = 2048,
        add_suffix: bool = True,
    ):
        self.processor = processor
        self.tokenizer = tokenizer
        self.image_token_id = None
        self.max_length = max_length
        self.suffix = ""

        if tokenizer is None and processor is None:
            raise ValueError("Either processor or tokenizer should be provided.")

        if self.processor is not None:
            self.image_token_id = self.processor.tokenizer.additional_special_tokens_ids[
                self.processor.tokenizer.additional_special_tokens.index("<image>")
            ]

            if self.tokenizer is not None:
                raise ValueError("Only one of processor or tokenizer should be provided.")

        if self.tokenizer and self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        if self.processor.__class__.__name__ == "PaliGemmaProcessor":
            if self.processor.tokenizer.padding_side != "right":
                print("Setting padding side to right")
                self.processor.tokenizer.padding_side = "right"

        if add_suffix:
            if self.tokenizer:
                self.suffix = self.tokenizer.pad_token * 10
            else:
                self.suffix = self.processor.tokenizer.pad_token * 10

    def __call__(self, examples):
        if self.processor is None:
            return self.forward_text(examples)
        if self.processor.__class__.__name__ == "Idefics2Processor":
            return self.forward_vision_idefics(examples)
        if self.processor.__class__.__name__ == "Idefics3Processor":
            return self.forward_vision_idefics3(examples)
        if self.processor.__class__.__name__ == "PaliGemmaProcessor":
            return self.forward_vision_pali(examples)
        raise ValueError("Processor not supported")

    def forward_text(self, examples):
        texts_doc = []
        texts_query = []
        for example in examples:
            text_query = example["query"] + self.suffix
            text_doc = example["doc"]

            texts_doc.append(text_doc.strip())
            texts_query.append(text_query.strip())

        batch_doc = self.tokenizer(
            texts_doc, max_length=self.max_length, padding="longest", truncation=True, return_tensors="pt"
        )
        batch_query = self.tokenizer(
            texts_query, max_length=self.max_length, padding="longest", truncation=True, return_tensors="pt"
        )

        # prefix each key with "doc_" or "query_" to avoid key conflicts
        batch_doc = {f"doc_{k}": v for k, v in batch_doc.items()}
        batch_query = {f"query_{k}": v for k, v in batch_query.items()}
        batch_doc.update(batch_query)

        return batch_doc

    def forward_vision_idefics(self, examples):
        texts_doc = []
        texts_query = []
        images = []
        for example in examples:
            image = example["image"]

            text_query = None
            if example["query"] is not None:
                query = example["query"] + self.suffix
                messages_query = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Question: {query}",
                            },
                        ],
                    },
                ]
                text_query = self.processor.apply_chat_template(messages_query, add_generation_prompt=False).strip()

            messages_doc = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe the image."},
                        {"type": "image"},
                    ],
                },
            ]

            text_doc = self.processor.apply_chat_template(messages_doc, add_generation_prompt=False)

            texts_doc.append(text_doc.strip())
            texts_query.append(text_query)
            images.append([image])

        batch_doc = self.processor(
            text=texts_doc, images=images, return_tensors="pt", padding="longest", max_length=self.max_length
        )

        batch_query = None
        if all([t is None for t in texts_query]):
            print("All queries are None. Returning None for all queries.")
        elif any([t is None for t in texts_query]):
            raise ValueError("Some queries are None. This collator does not support None queries yet.")
        else:
            batch_query = self.processor(
                text=texts_query, return_tensors="pt", padding="longest", max_length=self.max_length
            )

        # prefix each key with "doc_" or "query_" to avoid key conflicts
        batch_doc = {f"doc_{k}": v for k, v in batch_doc.items()}

        if batch_query is not None:
            batch_query = {f"query_{k}": v for k, v in batch_query.items()}
            batch_doc.update(batch_query)

        return batch_doc

    def forward_vision_idefics3(self, examples):
        texts_doc = []
        texts_query = []
        images = []
        for example in examples:
            image = example["image"]

            text_query = None
            if example["query"] is not None:
                query = example["query"] + self.suffix
                
                messages_query = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Question: {query}",
                            },
                            {"type": "image","image": image},
                        ],
                    },
                ]
                text_query = self.processor.apply_chat_template(messages_query, add_generation_prompt=False).strip()

            messages_doc = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe the image."},
                        {"type": "image","image": image},
                    ],
                },
            ]

            text_doc = self.processor.apply_chat_template(messages_doc, add_generation_prompt=False)

            texts_doc.append(text_doc.strip())
            texts_query.append(text_query)
            images.append([image])

        batch_doc = self.processor(
            text=texts_doc, images=images, return_tensors="pt", padding="longest", max_length=self.max_length
        )

        batch_query = None
        if all([t is None for t in texts_query]):
            print("All queries are None. Returning None for all queries.")
        elif any([t is None for t in texts_query]):
            raise ValueError("Some queries are None. This collator does not support None queries yet.")
        else:
            batch_query = self.processor(
            images=images,  # NOTE: the image is not used in batch_query but it is required for calling the processor
            text=texts_query,
            return_tensors="pt",
            padding="longest",
            max_length=self.max_length + self.processor.image_seq_len,
            )
            # del batch_query["pixel_values"]
            input_ids_size = batch_query["input_ids"].shape[1]
            end_of_utterance_token = batch_query["input_ids"][..., -1:] # to add to the end of the input_ids
            image_input_ids_length = self.processor.image_seq_len
            extra_ids = 7 # remove the extra tokens added by the processor (<fake_token_around_image><global-img><image><image>)
            batch_query["input_ids"] = torch.cat((batch_query["input_ids"][..., :input_ids_size - image_input_ids_length -extra_ids], end_of_utterance_token), dim=1)
            batch_query["attention_mask"] = torch.cat((batch_query["input_ids"][..., :input_ids_size - image_input_ids_length -extra_ids], end_of_utterance_token), dim=1)

        # prefix each key with "doc_" or "query_" to avoid key conflicts
        batch_doc = {f"doc_{k}": v for k, v in batch_doc.items()}

        if batch_query is not None:
            batch_query = {f"query_{k}": v for k, v in batch_query.items()}
            batch_doc.update(batch_query)

        return batch_doc

    def forward_vision_pali(self, examples):
        texts_doc = []
        texts_query = []
        images = []
        neg_images = []
        for example in examples:

            if example["image"] is None:
                raise ValueError("Image is None - This collator does not support None images yet.")

            image = example["image"].convert("RGB")
            images.append(image)
            texts_doc.append("Describe the image.")

            if "neg_image" in example and example["neg_image"] is not None:
                neg_image = example["neg_image"].convert("RGB")
                neg_images.append(neg_image)

            if example["query"] is None:
                texts_query.append(None)
            else:
                query = example["query"]
                query = f"Question: {query}"
                # add pad tokens
                query += self.suffix
                texts_query.append(query)

        batch_doc = self.processor(
            text=texts_doc,
            images=images,
            return_tensors="pt",
            padding="longest",
            max_length=self.max_length + self.processor.image_seq_length,
        )

        batch_neg_doc = None
        if len(neg_images) > 0:
            batch_neg_doc = self.processor(
                text=texts_doc,
                images=neg_images,
                return_tensors="pt",
                padding="longest",
                max_length=self.max_length + self.processor.image_seq_length,
            )

        batch_query = None
        # check if some but not all queries are None
        if all([t is None for t in texts_query]):
            print("All queries are None. Returning None for all queries.")
        elif any([t is None for t in texts_query]):
            # if it's the first query that is not None but the rest are None, then it's hard negatives
            raise ValueError("Some queries are None. This collator does not support None queries yet.")
        else:
            # NOTE: the image is not used in batch_query but it is required for calling the processor
            batch_query = self.processor(
                images=images,
                text=texts_query,
                return_tensors="pt",
                padding="longest",
                max_length=self.max_length + self.processor.image_seq_length,
            )
            del batch_query["pixel_values"]
            batch_query["input_ids"] = batch_query["input_ids"][..., self.processor.image_seq_length :]
            batch_query["attention_mask"] = batch_query["attention_mask"][..., self.processor.image_seq_length :]

        # prefix each key with "doc_" or "query_" to avoid key conflicts
        batch_doc = {f"doc_{k}": v for k, v in batch_doc.items()}

        if batch_query is not None:
            batch_query = {f"query_{k}": v for k, v in batch_query.items()}
            batch_doc.update(batch_query)
        if batch_neg_doc is not None:
            batch_neg_doc = {f"neg_doc_{k}": v for k, v in batch_neg_doc.items()}
            batch_doc.update(batch_neg_doc)

        return batch_doc
