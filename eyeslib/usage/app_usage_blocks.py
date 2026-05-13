
def is_overlaped(prev_block, curr_block):
    if curr_block[TIME_START] < prev_block[TIME_END]:
        return True
    
    return False

class AppUsageBlocks:
    def __init__(self, sorted_blocks):
        self.blocks = sorted_blocks
        self.cursor = 0

    def get_next_block(self):
        block = None

        i = self.cursor
        if i >= 0 and i < len(self.blocks):
            block =  self.blocks[i]
            self.cursor += 1

        return block

    def insert_block(self, block):
        self.blocks.insert(self.cursor, block)

    def separate_overlaped_blocks(self):
        stack = []
        processing_stack = False

        i = 0
        while i < len(self.blocks):
            curr_block = self.blocks[i]

            if len(stack) <= 0:
                stack.append(curr_block)
            elif is_overlaped(stack[-1], curr_block):
                stack.append(curr_block)
            else:
                # work on the stack to identify the overlaped time frame
                curr_stack_block = stack.pop()

                if processing_stack is False:    
                    # the top stack block
                    processing_stack = True

                    start_time = curr_stack_block[TIME_START]
                    end_time = curr_stack_block[TIME_END]
                    print_primary(curr_stack_block, start_time, end_time)
                else:                    
                    if curr_stack_block[TIME_START] < start_time:
                        print_primary(curr_stack_block, curr_stack_block[TIME_START], start_time)

                    if curr_stack_block[TIME_END] < end_time:
                        print_secondary(curr_stack_block, start_time, curr_stack_block[TIME_END])
                    else:
                        print_secondary(curr_stack_block, start_time, end_time)
                        
                        # create a new block (leftover from curr_stack_block)
                        new_block = create_new_block(curr_stack_block, end_time, curr_stack_block[TIME_END])
                        self.insert_block(new_block)

                    start_time = curr_stack_block[TIME_START]

                if len(stack) <= 0:
                    processing_stack = False
                    start_time = None
                    end_time = None

                continue

            i += 1
    